---
name: ai-hub-auth
description: 实现 AI Hub 统一鉴权系统的接入，支持 Cookie Token、Ticket 机制、OAuth2 授权码 SSO、SSO 钉钉登录等多种鉴权方式。当用户需要为子应用或外部应用接入 AI Hub 鉴权、实现统一登录验证、处理跨域鉴权、配置 Nginx auth_request 鉴权、实现独立应用 SSO 单点登录时使用此 skill。
---

# AI Hub 统一鉴权接入

## 环境信息

| 环境 | AI Hub 地址 | 说明 |
|------|------------|------|
| 公司内网 | `http://131.131.2.10:30080/` | 生产环境 |
| 腾讯云公网 | `http://111.229.103.94:30080/` | 测试环境 |
| 本地开发 | `http://localhost:30080/` | 本地 AI Hub 服务 |

> **重要**：AI Hub 地址不要硬编码，应放到配置文件中根据环境切换。

## 快速选择

```
你要做什么？
├── 用户怎么进入我的应用（登录）
│     ├── qiankun 微前端子应用（type=micro）→ 方式一：props 传递
│     ├── 与 AI Hub 同域部署               → 方式二：Cookie + nginx
│     ├── 只从 AI Hub 点击进入（跨域）      → 方式三：Ticket
│     └── 需要独立入口（直接打开）          → 方式四：OAuth2 授权码 SSO ★推荐
├── 我要调 AI Hub 的接口
│     ├── 有当前用户（用户态）              → 用户 access_token（401 则无感续期）
│     └── 纯服务行为（服务态）              → 方式五：AppAPIKey 调 /api/v1/common/*
├── 我要调其他子应用的接口（或被其他子应用 / AI Hub 调）
│     └── 方式六：直连 + introspect 验证 ★强制（备选代理 /api/v1/proxy/{对方code}/...）
└── 我要保护子应用自己的接口
      ├── 给浏览器用户用的（浏览器用，登录材料来自方式四 SSO）→ 本地 JWT
      └── 给其他子应用 / AI Hub 调的       → 方式六：introspect 验证
```

> **方式三 vs 方式四 的区别**：Ticket 机制要求用户必须从 AI Hub 点击跳转进入应用；OAuth2 授权码模式支持用户直接打开你的应用（新标签页），自动跳转 AI Hub 完成登录后回调。**如果你的应用需要独立访问入口，选择方式四。**

---

## 对接总则（必读）

### 凭证矩阵——按调用方向选凭证

| 调用方向 | 凭证 | 机制 |
|---------|------|------|
| 用户进子应用（登录） | — | 方式四 OAuth2（★独立入口）/ 方式三 Ticket / 方式二 Cookie+nginx |
| 子应用调 AI Hub（用户态） | AI Hub access_token | `Bearer` 调任意 `/api/v1/*` 用户接口 |
| 子应用调 AI Hub（服务态） | AppAPIKey（`ak-` 前缀） | `/api/v1/common/*` 双兼容鉴权 |
| 子应用 / AI Hub 调**其他子应用** | AI Hub 凭证（用户 access_token / AppAPIKey / 平台出站凭证） | **直连 + 自省（★强制，方式六）**：A 收到请求后调 `GET /api/v1/auth/introspect` 验证凭证再放行；备选代理 `/api/v1/proxy/{被调应用code}/{path}` |
| 子应用保护自己的接口 | 子应用本地 JWT | SSO 拿到 user 后自签，业务接口挂本地 JWT 依赖 |

### 核心原则

1. **子应用对外暴露的接口必须经 AI Hub 鉴权（强制规范）**——所有子应用的服务接口（供其他子应用或 AI Hub 调用）统一走 introspect 验证（方式六）：被调方把收到的 Bearer 凭证原样发给 `GET /api/v1/auth/introspect`，凭返回的调用方身份放行。**互发密钥被禁止**（调用方私有 key 会让密钥矩阵随应用数平方增长，且 AI Hub 无法审计），不允许无凭证裸接口、不信任内网来源。被调方建议对自省结果做短 TTL 缓存（如 60 秒）。
2. **应用间调用授权**：调用方应用在应用管理配置 `allowed_target_apps`（可调用的应用列表，None=不限制）；introspect 时 AI Hub 校验被调应用是否在列，不在列 403 拒绝——**对用户 token 与 AppAPIKey 两种凭证都生效**，token 无应用归属（AI Hub 自身登录）时跳过。**每次自省落调用日志**（`app_call_logs`：时间、调用方应用、用户、被调应用、接口路径、结果、来源 IP；90 天 TTL 自动清理），admin 在「调用日志」页查询。A 验证时传 `target_path`/`method` 参数可让日志完整记录被调接口。
3. **每个子应用只需处理两种凭证**：自己的本地 JWT（保护自己）+ AI Hub 凭证（access_token / AppAPIKey，调用别人，也被别人验证）。AI Hub 平台调用你时附带平台统一签发的凭证（平台 API Key / 用户代理 token），同一 introspect 验证即可识别，无需本地配置任何共享密钥。
4. **凭证语义**：用户的 access_token = 代理该用户操作（A 看到 `caller_type=user`；token 内含 `app_code` claim 标识签发来源应用）；AppAPIKey = 应用自身服务态调用（A 看到 `caller_type=app` + app_code）。个人数据类能力必须要求用户凭证，防止查任意用户数据。

### 无感续期（access_token 30 分钟过期）

```
接口返回 401
  → POST /api/v1/auth/refresh  { "refresh_token": "..." }   ← /token 时已下发
  → 拿新 access_token + refresh_token，重试原请求
  → refresh 也 401 → 重定向 /api/v1/auth/authorize 重走 SSO（AI Hub Cookie 在则静默跳回）
```

前端统一拦截 401 自动走这条链路，用户全程无感。

### 管理侧配置（管理员在 AI Hub 界面维护，无代码）

| 配置 | 位置 | 用途 |
|------|------|------|
| 应用注册（code / entry_url / type） | 应用管理 | SSO 与代理路由的标识 |
| required_permissions | 应用管理 → 编辑 | 应用访问白名单（SSO、代理、introspect 用户态共用） |
| allowed_target_apps | 应用管理 → 编辑 → 可调用的应用 | 应用间调用授权（方式六校验） |
| API 连接（base_url / 代理开关 / allowed_prefixes / 超时） | 应用管理 → 编辑 → API 连接 | 代理转发控制（出站凭证由平台统一持有，无共享密钥） |
| 服务级 API Key | 「服务级 API Key」页 | 子应用服务态调 /common 与其他子应用的凭证 |
| 应用内角色（app_roles） | 应用管理 → 编辑 → 应用内角色 | 「用户 × 应用」角色标签，子应用自行解释 |
| 调用日志 | 侧边栏「调用日志」（admin） | introspect 记录的子应用间调用审计 |

---

## 方式一：qiankun props

主应用传递的结构：

```ts
interface MicroAppProps {
  mainApp: {
    navigate: (path: string) => void;
    token: string | null;
    user: {
      id: string;
      username: string;
      role: 'admin' | 'department_admin' | 'employee';
      departmentId?: string;      // 所属部门 ID
      departmentName?: string;    // 所属部门名称
      appRoles: string[];   // 应用内角色标签，详见「应用内角色」
    } | null;
  };
}
```

子应用在 `mount(props)` 中取 `props.mainApp.user` 存入 Context，调 API 时带 `Authorization: Bearer ${token}`。空 `appRoles` 当"普通用户"处理。

---

## 方式二：Cookie + nginx auth_request

**架构**：用户访问 → nginx auth_request → 后端验证 Cookie → 放行/拒绝

```nginx
# 鉴权内部端点（不对外暴露）
location = /auth/verify {
    internal;
    proxy_pass http://backend:8000/api/v1/auth/verify;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
}

# 子应用代理（以 /subapps/ai-chat/ 为例）
location ^~ /subapps/ai-chat/ {
    auth_request /auth/verify;
    auth_request_set $user_id $upstream_http_x_user_id;
    auth_request_set $user_role $upstream_http_x_user_role;
    auth_request_set $app_roles $upstream_http_x_app_roles;

    error_page 401 = @login_redirect;
    error_page 403 = @forbidden;

    proxy_pass http://127.0.0.1:30002/;
    proxy_set_header X-User-Id $user_id;
    proxy_set_header X-User-Role $user_role;
    proxy_set_header X-App-Code ai-chat;          # 静态写死，让 verify 知道是哪个应用
    proxy_set_header X-App-Roles $app_roles;       # 透传应用内角色给子应用
}
```

`/auth/verify` 端点**优先从 `X-Original-URI`（nginx `$request_uri`）解析 `/subapps/{code}/` 前缀**确定应用，`X-App-Code` 头仅作无 URI 时的补充（不可优先信任——auth_request 子请求会透传客户端原始请求头，X-App-Code 可被伪造）。查 `app_member_roles` 后在响应头返回 `X-User-Id`/`X-User-Role`/`X-App-Roles`（逗号分隔），nginx 捕获后注入给子应用。无角色时不返回 `X-App-Roles` 头。

> 实际配置由后端自动生成：`GET /api/v1/apps/nginx-config` 为每个 `type=micro` 且配了 `container_port` 的应用生成上述 location 块。

前端获取用户：`fetch('/api/v1/auth/me', { credentials: 'include' })`

---

## 方式三：Ticket 机制（从 AI Hub 跳转的跨域场景）

**适用**：跨域外部链接应用（IP 相同端口不同也属于跨域），且用户从 AI Hub 中点击进入。

### 流程

```
AI Hub 生成 ticket → 跳转带 ?ticket=xxx → 外部应用验证 → 创建本地会话
```

### Ticket 特性

- **一次性**：验证后立即失效，不可重复使用
- **有效期**：30 秒，获取后需尽快验证
- **可选 `app_code`**：验证时 body 可带 `app_code`（应用编码），AI Hub 会一并返回该用户在该应用的 `app_roles`（应用内角色）。详见后文「应用内角色」。

### FastAPI + React 完整架构

> **注意区分两类端点**：下表是**你的应用自己要实现**的端点（前缀 `/api/auth`），用于接收 ticket 后创建本地会话。AI Hub 自身的端点前缀是 `/api/v1/auth/`（见后文「AI Hub API 端点」）。

**你的应用后端 API 设计：**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login/ticket` | POST | 接收 ticket，向 AI Hub `/api/v1/auth/verify-ticket` 验证并创建本地会话 |
| `/api/auth/me` | GET | 获取当前用户信息 |
| `/api/auth/logout` | POST | 销毁本地会话 |

**子应用侧实现**：后端 POST `/api/v1/auth/verify-ticket` 验证 ticket（body 可带 `app_code` 拿应用内角色），成功后签发本地 JWT；前端 `useEffect` 检测 URL 中 `?ticket=` 调用后端换用户。整体模式与方式四同构——把 `code` 换成 `ticket`、`/token` 换成 `/verify-ticket` 即可，详见方式四的前后端代码骨架。

---

## 方式四：OAuth2 授权码 SSO（独立应用，可单独打开）★推荐

**适用**：独立部署的外部应用，用户可以直接在浏览器中打开（不从 AI Hub 跳转），自动完成 SSO 登录。

### 核心优势

与 Ticket 机制的关键区别：**用户不需要从 AI Hub 点击进入**，可以直接打开你的应用 URL，自动跳转 AI Hub 完成登录验证后回调。

### 完整流程

```
用户直接打开你的应用（未登录）
  → 跳 AI Hub /api/v1/auth/authorize?redirect_uri=<回调URL>&app_code=<你的code>
      AI Hub 验 Cookie：已登录 → 校验 required_permissions → 签发一次性 code → 307 回调
                        未登录 → 登录页 → 登录后跳回 /authorize 续流程
                        权限不满足 → 停在 /no-app-access，不签发 code
  → 子应用后端：POST /api/v1/auth/token { "code" } → 拿到 access_token/refresh_token + user
  → 签发本地会话返回前端 → 前端清 URL 中的 code，进入应用
```

### Auth Code 特性

- **一次性**：验证后立即失效，不可重复使用
- **有效期**：60 秒，获取后需尽快验证
- **安全性**：code 通过 URL 参数传递，后端用后即焚

### 你的后端需要实现的端点

> **注意**：下表是**你的应用自己要实现**的端点（前缀 `/api/auth`），用于接收 auth code 后创建本地会话。AI Hub 自身的端点前缀是 `/api/v1/auth/`（见后文「AI Hub API 端点」）。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login/oauth2` | POST | 接收 auth code，向 AI Hub `/api/v1/auth/token` 验证并创建本地会话 |
| `/api/auth/me` | GET | 获取当前登录用户信息 |
| `/api/auth/logout` | POST | 销毁本地会话 |

> **取 app_roles**：`authorize(app_code)` → `/token` 两步即可，`/token` 响应已含 `user.app_roles`（authorize 会先做应用访问权限校验并审计）；需刷新角色时调 `/me?app_code=`。详见「AI Hub API 端点 → OAuth2 授权码」。

### 后端核心代码（FastAPI）

```python
@router.post("/login/oauth2")
async def oauth2_login(req: OAuth2CodeRequest):
    async with httpx.AsyncClient(timeout=10) as client:
        # 1. code 换 token + 完整用户信息（含 app_roles，由 authorize 传入的 app_code 决定）
        resp = await client.post(f"{AI_HUB_URL}/api/v1/auth/token", json={"code": req.code})
        if resp.status_code != 200:
            raise HTTPException(401, "授权码无效或已过期")
        data = resp.json()
        user = data["user"]

    # 2. 保存 AI Hub 的 access_token/refresh_token（供本应用后续调 AI Hub / 代理其他子应用；
    #    过期时调 /api/v1/auth/refresh 无感续期）
    save_aihub_tokens(user_id=user["id"],
                      access_token=data["access_token"],
                      refresh_token=data["refresh_token"])

    # 3. 签发本地 JWT（payload 带 app_roles），后续鉴权无需再调 AI Hub
    return {"token": create_your_local_jwt(user), "user": user}
```

> `AI_HUB_URL` 放配置文件按环境切换（见「环境信息」）。若需再调 `/me?app_code=` 补充/刷新角色，还需配置 `AI_HUB_APP_CODE`（与 AI Hub「应用管理」里注册的 code 一致）。`app_roles` 的消费方式见「应用内角色 → 子应用怎么消费」。

### 前端关键逻辑

```tsx
// 1. 检测 code → 调后端换用户，存 token 后清 URL
useEffect(() => {
  const code = new URLSearchParams(location.search).get('code');
  if (!code) return;   // 无 code：从 localStorage 恢复会话即可
  fetch('/api/auth/login/oauth2', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  })
    .then(res => res.json())
    .then(data => {
      localStorage.setItem('token', data.token);
      setUser(data.user);
      window.history.replaceState({}, '', window.location.pathname);
    });
}, []);

// 2. 登录按钮 → 跳 AI Hub authorize
const login = () => {
  const redirectUri = encodeURIComponent(`${window.location.origin}/auth/callback`);
  window.location.href =
    `${AI_HUB_URL}/api/v1/auth/authorize?redirect_uri=${redirectUri}&app_code=${APP_CODE}`;
};

// 3. 任何 AI Hub 接口返回 401 → 用 refresh_token 调 POST /api/v1/auth/refresh
//    续期后重试原请求；refresh 也 401 → 重跳 authorize（见「无感续期」）
```

> Ticket 与 OAuth2 共用同一套 `useAuth` 骨架：检测 URL 参数（`code`/`ticket`）→ 调后端换用户 → 存 token → 无参数时从 localStorage 恢复会话 → 失败降级游客。

路由只需两个页面：`/`（首页）+ `/auth/callback`（回调中转，处理 code 后跳首页）。游客模式可选，`const isGuest = !loading && !user` 控制是否展示「登录」按钮。

---

## 方式五：API Token（服务态调 AI Hub）

子应用后端/外部服务以**应用自身身份**调 AI Hub 通用接口（`/api/v1/common/*`）时用服务级 API Key：

```http
GET /api/v1/common/apps/{app_code}/roles
Authorization: Bearer ak-xxxx
```

- `ak-` 前缀 key 由 admin 在 AI Hub「API Key 管理」页创建，**绑定一个 app_code**（隔离边界，不是全局万能 key）
- 双兼容鉴权：`ak-` 前缀走 API Key（身份=应用），否则按用户 JWT 解析
- 需要用户态语义时不用 AppAPIKey——改用用户的 access_token（见「凭证语义」，个人数据必须用户凭证）

---

## SDK API 参考

引入（二选一）：动态端点 `/api/v1/auth/sdk.js`（推荐，始终与后端版本一致）或静态 `/aihub-auth-sdk.js`。

| 方法 | 说明 | 返回值 |
|------|------|--------|
| `AiHubAuth.autoAuth()` | 自动选择鉴权方式（优先 ticket，其次 cookie） | `Promise<User \| null>` |
| `AiHubAuth.verifyTicket()` | 验证 URL 中的 ticket 参数 | `Promise<User \| null>` |
| `AiHubAuth.getUserInfo()` | 通过 Cookie 获取用户信息（调 `/auth/me`） | `Promise<User \| null>` |

### 应用内角色：`window.AiHubAppCode` 约定

需要 `app_roles` 时，在引入 SDK**之前**设 `window.AiHubAppCode = 'ai-chat'`。设后 `verifyTicket` 调用 body 带 `app_code`、`getUserInfo` URL 带 `?app_code=`，返回的 user 含 `app_roles`。不设则不带、`app_roles` 为 `[]`。

> SDK 不支持 OAuth2 授权码模式（需后端参与 code 换 token），请参考方式四。

---

## AI Hub API 端点

### 鉴权相关

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/login` | POST | 用户名密码登录 |
| `/api/v1/auth/refresh` | POST | 刷新 access token |
| `/api/v1/auth/me` | GET | 获取当前用户（需 Bearer token）。支持 `?app_code=` 可选参数，传则响应附带 `app_roles` |
| `/api/v1/auth/introspect` | GET | 凭证自省（方式六验证端点）：验证 Bearer 凭证（用户 JWT 或 ak- Key），返回 `caller_type`/`user_id`/`app_code`/`app_roles`；`?app_code=` 触发访问白名单 + 应用间授权校验；`?target_path=&method=` 记入调用日志 |
| `/api/v1/auth/verify` | GET | nginx 内部鉴权端点，按 `X-App-Code` 头返回 `X-User-Id`/`X-User-Role`/`X-App-Roles` 响应头 |
| `/api/v1/auth/set-cookie` | POST | 将 token 写入 HttpOnly Cookie |
| `/api/v1/auth/clear-cookie` | POST | 登出时清除 Cookie |
| `/api/v1/auth/set-password` | POST | 设置/修改密码（已设密码需验旧密码） |
| `/api/v1/auth/sdk.js` | GET | 动态返回鉴权 SDK 脚本（内容与静态 `/aihub-auth-sdk.js` 一致） |

### Ticket 机制（方式三）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/ticket` | POST | 获取一次性 ticket（需 Authorization） |
| `/api/v1/auth/verify-ticket` | POST | 验证 ticket，返回用户信息（用后即焚）。body 可带 `app_code`，传则响应附带 `app_roles` |

### OAuth2 授权码（方式四）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/authorize` | GET | 授权入口，验证 Cookie + 应用访问权限后签发一次性 auth code |
| `/api/v1/auth/token` | POST | 外部应用后端用 auth code 换取用户信息 + access token |

**`/authorize` 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `redirect_uri` | 是 | 授权成功后的回调 URL（需 URL 编码） |
| `app_code` | 否 | 应用标识。**用于应用访问权限校验**（命中 `required_permissions`）及审计日志追踪。不传则跳过权限校验 |

> **`/authorize` 应用访问权限校验（应用级白名单）**：传了 `app_code` 且该应用在「应用管理」里配了 `required_permissions`（如 `{"roles": ["admin"]}` 或 `{"departments": [...]}`），AI Hub 会校验当前用户是否满足该白名单：
> - **满足 / 应用未配权限 / app_code 为空或 app 不存在** → 正常签发 code，307 跳回 `redirect_uri?code=xxx`
> - **不满足**（已登录但角色/部门不符）→ **停在 AI Hub 无权限页 `/no-app-access?app_code=...`**，**不签发 code、不跳回子应用**
>
> 注意：应用访问权限（白名单，决定"能不能进应用"）与应用内角色 `app_roles`（标签，决定"进应用后能做什么"）是两个独立维度。前者由 `required_permissions` 控制，后者由 `AppMemberRole` 控制。详见后文「应用内角色」。
> 未登录用户走到 `/authorize` 时，会先重定向到 AI Hub 登录页（`redirect` 参数完整携带 `redirect_uri`/`app_code`，登录成功后整页跳回 `/authorize` 继续授权流程）。

**`/token` 请求体：**

```json
{ "code": "授权码" }
```

> `/token` **只接受 `code`，不接受 `app_code`**。但响应里的 `user.app_roles` **直接包含角色**（由 `/authorize` 传入的 `app_code` 决定），无角色时为 `[]`。

**`/token` 响应体：**

```json
{
  "access_token": "AI Hub JWT token",
  "refresh_token": "AI Hub refresh token（调 /auth/refresh 无感续期用）",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": { "…": "与下文 UserInfoResponse 结构一致，此处省略" }
}
```

---

## 用户信息结构

`/auth/me`、`/auth/verify-ticket`、`/auth/token` 三个通道返回**同一份结构**（`UserInfoResponse`，上述 14 字段）。`department_name` 为部门名称（未绑定部门时 `null`），与 `department_id` 成对出现。

```json
{
  "id": "6650a1b2c3d4e5f6",
  "username": "zhangsan",
  "real_name": "张三",
  "email": "zhangsan@example.com",
  "phone": "13800000000",
  "avatar_url": null,
  "role": "employee",
  "department_id": "6650a1b2c3d4e5f7",
  "department_name": "技术部",
  "status": "active",
  "has_password": true,
  "dingtalk_user_id": null,
  "dingtalk_union_id": null,
  "app_roles": []
}
```

> **`app_roles`**：默认 `[]`（空数组）。仅当请求带 `app_code`（`/me` 用 `?app_code=`，`verify-ticket` 用 body）且该用户在该应用有角色时才填充角色数组（如 `["prompt-manager"]`），否则为 `[]`。

**系统角色（全局）：**

| 角色 | 权限范围 |
|------|---------|
| `admin` | 全部权限 |
| `department_admin` | 本部门用户管理 |
| `employee` | 仅个人设置 |

> 系统角色全局有效。应用内角色 `app_roles` 是"用户×应用"维度标签，与系统角色独立，由子应用自行解释。详见后文「应用内角色」。

---

## 应用内角色

平台支持给「用户 × 应用」打任意字符串角色标签（如 `prompt-manager`、`ops`、`admin`）。**平台只存不解释**，子应用自行决定标签含义（例如 ai-chat 子应用把 `prompt-manager` 当成可管理 prompt 的用户）。系统角色（admin/department_admin/employee）与应用内角色是两个独立维度——一个普通员工可以在某个应用里被授予应用管理员标签。

### 分配入口

admin 在 AI Hub「应用管理」→ 编辑应用 → 「应用内角色」配置块中给用户打标签。

### `app_code` 是什么、从哪来

`app_code` 是你在 AI Hub「应用管理」**创建应用时自己填写**的应用编码（如 `ai-chat`），不是平台分配的随机 ID，平台据此查 `app_member_roles` 返回对应角色。三种读取通道各需一份，配置位置不同：

| 通道 | app_code 配在哪 | 标准配置项 |
|------|---------------|-----------|
| 方式二 nginx | nginx location 块静态写死（`/nginx-config` 自动生成） | 自动 |
| 方式三 SDK | 子应用前端，引入 SDK 前设全局变量 | `window.AiHubAppCode = 'ai-chat'` |
| 方式四 OAuth2 | 后端配置项 + 前端 env（可选） | 后端 `AI_HUB_APP_CODE`；前端 `VITE_AI_HUB_APP_CODE` |

> **方式四后端那份是必需的**（`/token` 响应已含 `app_roles`，由 authorize 传入的 `app_code` 决定），前端那份可选（带上去 authorize 仅审计用）。改名 `app_code` 不丢角色（`app_member_roles` 按 `app_id` 存），但前后端硬编码的旧 code 会失效。

### 三条读取通道

| 通道 | 适用场景 | 字段位置 |
|------|---------|---------|
| qiankun props | qiankun 微前端子应用 | `props.mainApp.user.appRoles: string[]` |
| nginx header | 经 nginx 代理的同域/独立 Web 应用 | `X-App-Roles` 响应头（逗号分隔） |
| ticket / SDK | 跨域外部应用 | `verify-ticket` 传 `app_code` 或 `/me?app_code=`，响应含 `app_roles` |

**约定**：空 `app_roles`（无标签）当作"普通用户"处理。

### 子应用怎么消费（推荐 OR 叠加判断）

`app_roles` 写入本地 JWT 后，`get_current_user` 解 token 即可暴露。系统 `role` 全局（admin 全通），`app_roles` 是"用户×应用"维度标签，推荐 OR 形式判断——admin 总有权限，普通员工需被打标签。

```python
# 后端：需要某应用的 kb-manager 权限，或系统 admin
def require_kb_manager(user = Depends(get_current_user)):
    if "kb-manager" not in (user.app_roles or []) and user.role != "admin":
        raise HTTPException(403, "无权限")
```

```ts
// 前端：按 app_roles 控制功能可见性
const canManageKb = user.app_roles?.includes('kb-manager') || user.role === 'admin';
{canManageKb && <Button>管理知识库</Button>}
```

### 管理端点（仅 admin）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/apps/{app_id}/members` | GET | 列出某应用所有成员及其角色 |
| `/api/v1/apps/{app_id}/members` | POST | 给某用户设置角色（新增或覆盖，幂等） |
| `/api/v1/apps/{app_id}/members/{user_id}` | PUT | 修改某用户角色（传空数组等同删除） |
| `/api/v1/apps/{app_id}/members/{user_id}` | DELETE | 移除某用户在该应用的所有角色 |

> 仅 admin 可调，子应用一般不直接调用。

---

## 方式六：应用间调用（直连 + introspect 验证）★强制

**强制规范：AI Hub 的所有子应用，对外暴露的服务接口（供其他子应用或 AI Hub 调用）必须经 AI Hub 鉴权**——被调方把收到的 Bearer 凭证原样发给 `GET /api/v1/auth/introspect` 验证后放行。不接受调用方私有密钥（互发密钥被禁止，见「核心原则 1」）、不允许无凭证裸接口、不信任内网来源。

**适用**：调用其他子应用的接口（如对话应用调网关的 api-key 接口）；接口被其他子应用调用；接口被 AI Hub 平台调用（统一待办聚合、AI 跨应用查数据等）；用户经 `/api/v1/proxy/{你的code}/...` 代理调用（需管理员在「API 连接」开启 `proxy_enabled` 并配置 `allowed_prefixes` 白名单）。

### 调用方：怎么调其他子应用的接口

前提：

1. **目标应用的内网 API 地址**：由部署方提供（写入你的 config 按环境切换；AI Hub 不集中分发部署拓扑）
2. **凭证**（二选一，见下）：服务态用你自己的服务级 API Key；用户态用当前用户的 access_token
3. 如需限定调用范围：管理员在你的应用「应用管理 → 可调用的应用」（`allowed_target_apps`）勾选目标应用（不配置 = 不限制）

服务态调用（你的后端 → 对方后端，以应用自身身份）：

```python
# your_app/services/gateway_client.py
resp = await httpx.get(
    f"{TARGET_APP_URL}/api/user/api-key",     # 目标子应用内网 API 地址
    headers={"Authorization": f"Bearer {MY_APP_API_KEY}"},  # 你的 ak- Key（AI Hub「服务级 API Key」页创建）
)
# 对方会把该凭证发 AI Hub introspect，验证 caller_type=app / app_code=你的code 后放行
```

用户态调用（代理当前用户操作，用登录时拿到的用户 access_token）：

```python
resp = await httpx.post(
    f"{TARGET_APP_URL}/api/items",
    headers={"Authorization": f"Bearer {user_access_token}"},
    json={"title": "x"},
)
```

- 目标返回 401 且你用的是用户 access_token → 先走无感续期链路（见「无感续期」）再重试
- 目标返回 403 `该应用未被授权调用目标应用` → 管理员在你的应用勾选 `allowed_target_apps`
- 目标返回 403 `无访问该应用的权限` → 当前用户不满足目标应用的访问白名单（`required_permissions`）

备选：**AI Hub 代理转发**（前端直调场景）——带用户 access_token 调 AI Hub 的 `ANY /api/v1/proxy/{对方code}/{path}`，AI Hub 五重校验（登录/应用 active/代理开关/路径白名单/应用访问权限）后以用户身份转发。适合前端直调、需要集中白名单防护的低频管理类调用；高频业务调用走上面的直连 + 自省。

### 被调方：怎么验证（所有调用方通用）

调用方凭证（全部由 AI Hub 统一签发）：

| 调用方 | 凭证 | introspect 返回 |
|--------|------|----------------|
| 子应用（代理某用户） | 用户的 access_token | `caller_type=user` + `user_id` |
| 子应用（服务态） | 调用方应用的服务级 API Key | `caller_type=app` + `app_code` |
| AI Hub 平台（服务身份） | 平台 API Key（平台统一持有） | `caller_type=app`，`app_code="ai-hub"` |
| AI Hub 平台（代理用户） | 用户代理 token（短时 JWT，仅限身份验证） | `caller_type=user` + `user_id` |

协议要点：

- 被调方（A）验证时把调用方凭证原样放进 `Authorization` 头调 AI Hub：
  `GET /api/v1/auth/introspect?app_code=你的应用code&target_path=收到请求的路径&method=请求方法`
- AI Hub 返回 `200 {valid, caller_type, user_id/app_code, app_roles}` 或 `401/403`（无效/未授权）
- 建议对自省结果按凭证做**短 TTL 缓存（如 60 秒）**，减少每次调用的验证开销
- AI Hub 侧同时校验：调用方应用的 `allowed_target_apps` 是否含你的应用（未配置=不限制）、用户态时的应用访问白名单，并落调用日志（谁在哪个应用调了哪个应用的哪个接口）

验证依赖（FastAPI，~25 行，所有调用方通用）：

```python
# your_app/core/aihub_verify_credential.py
import httpx
from fastapi import HTTPException, Request

AI_HUB_URL = settings.ai_hub.url        # 按环境切换
MY_APP_CODE = settings.ai_hub.app_code  # 你在 AI Hub 注册的应用 code


async def verify_aihub_credential(request: Request) -> dict:
    """验证请求方的 AI Hub 凭证（直连 + 自省模式）。

    返回自省结果（caller_type / user_id / app_roles），失败抛 401。
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "缺少 AI Hub 凭证")
    # 建议此处加 TTL 缓存（token → 自省结果），消除每请求一跳开销
    resp = await httpx.get(
        f"{AI_HUB_URL}/api/v1/auth/introspect",
        params={"app_code": MY_APP_CODE,
                "target_path": request.url.path, "method": request.method},
        headers={"Authorization": auth},
    )
    if resp.status_code != 200:
        raise HTTPException(401, "凭证无效或无权限")
    return resp.json()   # caller_type / user_id / app_roles


@router.get("/api/user/api-key")
async def get_user_api_key(caller: dict = Depends(verify_aihub_credential)):
    if caller["caller_type"] != "user":
        raise HTTPException(403, "个人数据需用户凭证")   # 防止服务态查任意用户数据
    user_id = caller["user_id"]
    # 以 user_id 查询该用户自己的数据
    ...
```

路由按调用方圈定数据范围：`caller_type=user` → 代理该用户操作（`user_id` 可信，AI Hub 验证背书）；`caller_type=app` 且 `app_code == "ai-hub"` → AI Hub 平台服务身份（平台级聚合数据）；其他 `app_code` → 对方应用服务态。

需要用户详情（姓名、部门）时，用你的服务级 API Key 调 AI Hub：

```python
# POST /api/v1/common/users/batch  {"user_ids": [user_id]}（单次最多 200 个）
# Authorization: Bearer ak-xxxx（AI Hub 应用管理创建的服务级 API Key）
```

### 授权与调用日志（AI Hub 自动执行，无需子应用代码）

- **应用间调用授权**：调用方应用在「应用管理 → 可调用的应用」（`allowed_target_apps`）勾选可调用的应用；introspect 时校验被调应用是否在列，不在列 403 拒绝——对用户 token 与 AppAPIKey 两种凭证都生效，token 无应用归属时跳过。不配置 = 不限制。
- **调用日志**：每次 introspect 验证落一条 `app_call_logs`（时间、调用方应用、用户、被调应用、接口路径与方法、结果、来源 IP；90 天 TTL 自动清理）。被调方验证时传 `target_path`/`method`（上面依赖代码已带）可让日志记录完整接口路径。admin 在 AI Hub「调用日志」页或 `GET /api/v1/app-call-logs` 查询。

---

## 关键实践要点

1. **AI Hub 地址按环境配置**：后端放配置文件，前端按 hostname 判断 `localhost → localhost:30080`，否则内网地址。
2. **跨域判断**：同 IP 不同端口即跨域，Cookie 不可用，必须用 Ticket 或 OAuth2 授权码。
3. **React StrictMode 重复消费**：useEffect 执行两次会让一次性 ticket/code 被消费两次致 401，用 `Set` 缓存已验证的值。
4. **验证失败降级**：ticket/code 验证失败不阻塞应用，降级游客模式继续浏览；失败时打日志 `logger.warning(f"验证失败: status={response.status_code}, body={response.text}")`。
5. **OAuth2 回调**：`/api/v1/auth/token` 只接受 POST，code 必须由后端服务端换取（避免暴露在浏览器日志）；回调 URL 用专用路由 `/auth/callback`，不要附业务参数。

---

## 常见问题

### ticket/code 验证 401 无效或已过期

- 已被使用（一次性）或超时（ticket 30s / code 60s）
- React StrictMode 重复执行（见实践要点 3）
- 前端直接用 GET 请求了 `/token`（必须 POST，由后端调）
- AI Hub 地址配置错误

### 重定向到 AI Hub 后没有回调

- `redirect_uri` 未正确 URL 编码
- AI Hub 不可达（网络/DNS）或浏览器 CORS 错误

### 回调后停在 `/no-app-access` 无权限页

- 当前用户不满足该应用 `required_permissions`（角色/部门白名单）
- 联系管理员在「应用管理」调整白名单，或清空 `required_permissions` 取消限制

### 获取不到用户信息

- qiankun：检查 mount 是否接收 `props.mainApp.user`
- Cookie：检查 `credentials: 'include'` 和 Cookie 是否存在
- Ticket/OAuth2：检查 code 是否被前端直接消费（应由后端调用）

### introspect 返回 403

- `该应用未被授权调用目标应用`：调用方应用在「应用管理 → 可调用的应用」未勾选被调应用（`allowed_target_apps` 白名单），勾选即可
- `无访问该应用的权限`：调用方用户不满足被调应用的 `required_permissions` 访问白名单

### 本地开发验证一直失败

- 确认 AI Hub 地址指向本地（localhost:30080）
- 重启后端使配置生效
- 检查本地 AI Hub 服务是否正常运行
