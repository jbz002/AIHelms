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
应用类型判断：
├── qiankun 微前端子应用（type=micro）→ 方式一：props 传递
├── 同域名独立 Web 应用             → 方式二：Cookie + nginx
├── 跨域外部链接（type=link）       → 方式三：Ticket 机制
├── 独立部署的外部应用（可独立打开） → 方式四：OAuth2 授权码 SSO ★推荐
└── 纯后端 API 调用                 → 方式五：API Token
```

> **方式三 vs 方式四 的区别**：Ticket 机制要求用户必须从 AI Hub 点击跳转进入应用；OAuth2 授权码模式支持用户直接打开你的应用（新标签页），自动跳转 AI Hub 完成登录后回调。**如果你的应用需要独立访问入口，选择方式四。**

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

`/auth/verify` 端点按请求 `X-App-Code` 头查 `app_member_roles`，在响应头返回 `X-User-Id`/`X-User-Role`/`X-App-Roles`（逗号分隔），nginx 捕获后注入给子应用。无角色时不返回 `X-App-Roles` 头。

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
┌──────────────────────────────────────────────────────────────┐
│  用户直接打开你的应用（新标签页，不从 AI Hub 跳转）            │
│       │                                                      │
│       ▼                                                      │
│  你的前端：检测未登录                                         │
│       │                                                      │
│       ▼                                                      │
│  重定向到 AI Hub 授权页：                                     │
│  GET /api/v1/auth/authorize?redirect_uri=你的回调URL&app_code=你的应用code│
│       │                                                      │
│       ▼                                                      │
│  AI Hub 检查用户 Cookie：                                     │
│  ├── 已登录 → 校验应用访问权限 → 生成一次性 auth code → 307 回  │
│  └── 未登录 → 显示 AI Hub 登录页 → 登录后整页跳回 /authorize   │
│       │      继续校验 → 生成 code → 307 跳回你的回调URL        │
│  ⚠ 已登录但不满足 required_permissions → 停在 /no-app-access   │
│       │                                                      │
│       ▼                                                      │
│  你的后端收到回调（带 ?code=xxx）：                            │
│  POST /api/v1/auth/token  { "code": "xxx" }                  │
│       │                                                      │
│       ▼                                                      │
│  AI Hub 返回：{ access_token, user: { id, username, ... } }   │
│       │                                                      │
│       ▼                                                      │
│  你的后端：创建本地会话（JWT/Session），返回给前端              │
│       │                                                      │
│       ▼                                                      │
│  前端：清除 URL 中的 code，存储本地 token，进入应用            │
└──────────────────────────────────────────────────────────────┘
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

> **取 app_roles 的唯一链路（重要）**：
> - `/api/v1/auth/token` 响应里的 `user` **永远不含 `app_roles`**（代码未实现，即便 authorize 传了 app_code 也不会回填）。
> - `/api/v1/auth/authorize` 的 `app_code` 参数**用于应用访问权限校验 + 审计日志**。有 `required_permissions` 时校验不通过会停在 `/no-app-access`，不签发 code。
> - **拿到 app_roles 的唯一方式**：拿到 `/token` 返回的 `access_token` 后，**再调一次** `GET /api/v1/auth/me?app_code=<你的应用code>`（Bearer token 鉴权），响应会附带 `app_roles: string[]`。
>
> 即：`authorize(app_code)` → `token` → `me?app_code=` 三步，前两步拿不到角色，**第三步才拿得到**。`app_code` 在 authorize 传只是为了审计，在 me 传才触发角色返回。

### 后端核心代码（FastAPI）

```python
@router.post("/login/oauth2")
async def oauth2_login(req: OAuth2CodeRequest):
    async with httpx.AsyncClient(timeout=10) as client:
        # 1. code 换 token + 基础用户信息（无 app_roles）
        resp = await client.post(f"{AI_HUB_URL}/api/v1/auth/token", json={"code": req.code})
        if resp.status_code != 200:
            raise HTTPException(401, "授权码无效或已过期")
        data = resp.json()
        user, ai_hub_token = data["user"], data["access_token"]

        # 2. 补取应用内角色
        me = await client.get(
            f"{AI_HUB_URL}/api/v1/auth/me",
            params={"app_code": AI_HUB_APP_CODE},
            headers={"Authorization": f"Bearer {ai_hub_token}"},
        )
        user["app_roles"] = (me.json().get("app_roles") or []) if me.status_code == 200 else []

    # 3. 签发本地 JWT（payload 带 app_roles），后续鉴权无需再调 AI Hub
    return {"token": create_your_local_jwt(user), "user": user}
```

> `AI_HUB_URL` / `AI_HUB_APP_CODE` 放配置文件按环境切换（见「环境信息」），`AI_HUB_APP_CODE` 需与 AI Hub「应用管理」里注册的 code 一致。

### 消费 app_roles

`app_roles` 写入本地 JWT 后，`get_current_user` 解 token 即可暴露。叠加规则：系统 `role` 全局（admin 全通），`app_roles` 是"用户×应用"维度标签，推荐 OR 形式判断——admin 总有权限，普通员工需被打标签。

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
```

> Ticket 与 OAuth2 共用同一套 `useAuth` 骨架：检测 URL 参数（`code`/`ticket`）→ 调后端换用户 → 存 token → 无参数时从 localStorage 恢复会话 → 失败降级游客。

路由只需两个页面：`/`（首页）+ `/auth/callback`（回调中转，处理 code 后跳首页）。游客模式可选，`const isGuest = !loading && !user` 控制是否展示「登录」按钮。

---

## 方式五：API Token

```ts
fetch('/api/resource', { headers: { Authorization: `Bearer ${token}` } })
```

---

## SDK API 参考

引入（二选一）：动态端点 `/api/v1/auth/sdk.js`（推荐，始终与后端版本一致）或静态 `/aihub-auth-sdk.js`。

| 方法 | 说明 | 返回值 |
|------|------|--------|
| `AiHubAuth.autoAuth()` | 自动选择鉴权方式（优先 ticket，其次 cookie） | `Promise<User \| null>` |
| `AiHubAuth.verifyTicket()` | 验证 URL 中的 ticket 参数 | `Promise<User \| null>` |
| `AiHubAuth.getUserInfo()` | 通过 Cookie 获取用户信息（调 `/auth/me`） | `Promise<User \| null>` |

### 应用内角色：`window.AiHubAppCode` 约定

需要 `app_roles` 时，在引入 SDK**之前**设 `window.AiHubAppCode = 'ai-chat'`。设后 `verifyTicket` 调用 body 带 `app_code`、`getUserInfo` URL 带 `?app_code=`，返回的 user 含 `app_roles`。不设则不带、`app_roles` 为 `null`。

> SDK 不支持 OAuth2 授权码模式（需后端参与 code 换 token），请参考方式四。

---

## AI Hub API 端点

### 鉴权相关

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/login` | POST | 用户名密码登录 |
| `/api/v1/auth/refresh` | POST | 刷新 access token |
| `/api/v1/auth/me` | GET | 获取当前用户（需 Bearer token）。支持 `?app_code=` 可选参数，传则响应附带 `app_roles` |
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

### OAuth2 授权码（方式四）★新增

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

> `/token` **只接受 `code`，不接受 `app_code`**。即便你在 `/authorize` 时传了 `app_code`，`/token` 响应的 `user` 也**不含 `app_roles`**。要拿应用内角色，必须用返回的 `access_token` 再调 `GET /auth/me?app_code=`。

**`/token` 响应体：**

```json
{
  "access_token": "AI Hub JWT token",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "6650a1b2c3d4e5f6",
    "username": "zhangsan",
    "real_name": "张三",
    "email": "zhangsan@example.com",
    "role": "employee",
    "department_id": "6650a1b2c3d4e5f7"
  }
}
```

> `user` 里没有 `app_roles` 字段——需要应用内角色请走 `/me?app_code=`。

---

## 用户信息结构

`/auth/me` 返回（`CurrentUserResponse`）：

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
  "status": "active",
  "has_password": true,
  "dingtalk_user_id": null,
  "app_roles": null
}
```

`/auth/verify-ticket` 返回结构更精简（无 `phone`/`avatar_url`/`status`/`has_password`/`dingtalk_user_id`），其余字段一致。

> **`app_roles`**：仅当请求带 `app_code`（`/me` 用 `?app_code=`，`verify-ticket` 用 body）时才返回该应用的角色数组（如 `["prompt-manager"]`），否则为 `null`。

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

> **方式四后端那份是必需的**（调 `/me?app_code=` 才能拿 `app_roles`），前端那份可选（带上去 authorize 仅审计用）。改名 `app_code` 不丢角色（`app_member_roles` 按 `app_id` 存），但前后端硬编码的旧 code 会失效。

### 三条读取通道

| 通道 | 适用场景 | 字段位置 |
|------|---------|---------|
| qiankun props | qiankun 微前端子应用 | `props.mainApp.user.appRoles: string[]` |
| nginx header | 经 nginx 代理的同域/独立 Web 应用 | `X-App-Roles` 响应头（逗号分隔） |
| ticket / SDK | 跨域外部应用 | `verify-ticket` 传 `app_code` 或 `/me?app_code=`，响应含 `app_roles` |

**约定**：空 `app_roles`（无标签）当作"普通用户"处理。

### 管理端点（仅 admin）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/apps/{app_id}/members` | GET | 列出某应用所有成员及其角色 |
| `/api/v1/apps/{app_id}/members` | POST | 给某用户设置角色（新增或覆盖，幂等） |
| `/api/v1/apps/{app_id}/members/{user_id}` | PUT | 修改某用户角色（传空数组等同删除） |
| `/api/v1/apps/{app_id}/members/{user_id}` | DELETE | 移除某用户在该应用的所有角色 |

> 仅 admin 可调，子应用一般不直接调用。

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

### 本地开发验证一直失败

- 确认 AI Hub 地址指向本地（localhost:30080）
- 重启后端使配置生效
- 检查本地 AI Hub 服务是否正常运行
