---
name: aihub-integration
description: AI Hub 服务间集成对接指南。AI Hub 后端每次请求带 HMAC-SHA256 签名头（X-AIHub-Timestamp/Signature/On-Behalf-Of）直接调 AIHelms，拉取用户的 AI 身份（主 key、场景 key、绑定资源）。当用户需要"登录 AI Hub 后自动获取该用户在 AIHelms 的 AI key"、开发 AIHub→AIHelms 服务间身份供给、排查签名 401 报错、办理密钥轮换时使用此 skill。
---

# AIHelms 服务间集成对接（HMAC 验签，方式六）

## 适用场景

用户登录 AI Hub 后，AI Hub 的应用（如员工 ai chat）需要拿到该用户在 AIHelms 的 AI 身份（key 等），用于绑定个人模型调用。本通道提供"登录即拉取"的自动供给，**无需用户手动复制 key，也不使用长期 API Key**。

鉴权采用 HMAC 签名直连：AI Hub 每次请求自带签名头，AIHelms 验签放行。**无令牌交换、无令牌缓存、无密钥对**，每请求一次 HMAC 计算。

## 环境信息

| 环境 | AIHelms API 地址 | LiteLLM 调用地址（key 的实际使用端点） | 集成通道状态 |
|------|-----------------|--------------------------------------|-------------|
| 公司内网（生产） | `http://131.131.2.10:30700/api/v1` | `http://131.131.2.10:30710/v1` | 按本方案联调 |
| 本地开发（联调） | `http://localhost/api/v1` | `http://localhost:4000/v1` | 按本地 `.env` 配置 |

> 端点全 URL = 上表地址 + 下文路径，如 `http://131.131.2.10:30700/api/v1/integration/identity`。

## 整体流程

```
用户登录 AI Hub
   │
   ▼
AI Hub 后端：为请求计算 HMAC 签名（共享密钥 sk-conn-...）
   每次请求带三头：
     X-AIHub-Timestamp:    Unix 秒
     X-AIHub-Signature:    v1=<hex(HMAC-SHA256)>
     X-AIHub-On-Behalf-Of: 该用户在 AI Hub 的 user_id
   │
   ▼
GET /integration/identity
   │  AIHelms 验签（时间戳 ±300s + 签名比对）
   │  按 On-Behalf-Of 定位用户（首次出现自动建档并开通个人主 key）
   ▼
返回该用户全量 AI 身份：personal / department / project 三组 key
   │
   ▼
AI Hub 缓存身份，给下游应用绑定 key；
用户实际调模型 = 拿 key 打 LiteLLM 调用地址
```

## 准备工作

### 1. 拿到共享密钥（sk-conn-...）

| 项 | 说明 |
|------|------|
| 来源 | AI Hub 应用管理「编辑应用 → API 连接」生成的共享密钥（sk-conn-...），或双方协商生成一个等长随机串 |
| AI Hub 侧 | 存后端配置（环境变量/密钥管理器），**不进仓库/前端/日志** |
| AIHelms 侧 | 配置到 `.env` 的 `AIHUB_INTEGRATION_HMAC_SECRET` |

> 密钥通过私密渠道交付（内网共享/加密压缩/密码另途），**不走群聊/邮件明文附件**。密钥为对称密钥，两侧须完全一致。

### 2. AIHelms 侧配置清单

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `AIHUB_INTEGRATION_HMAC_SECRET` | `sk-conn-...` | 空 = 集成通道关闭（所有集成请求 401） |
| 时间容差 | ±300 秒 | 双方服务器 NTP 需同步，偏差 ≤ 300 秒 |

## 签名规范

每次请求构造签名串（`\n` 连接六个字段）：

```
v1\n{timestamp}\n{METHOD}\n{path_with_query}\n{sha256_hex(body)}\n{on_behalf_of 或空}
```

| 字段 | 规则 |
|------|------|
| `v1` | 固定版本串 |
| `timestamp` | Unix 秒，与 AIHelms 服务器时钟偏差 ≤ 300 秒 |
| `METHOD` | HTTP 方法大写（GET/POST/...） |
| `path_with_query` | 请求路径（URL 解码后）+ `"?" + query`（query 保持原始编码，Starlette `request.url` 语义） |
| `sha256_hex(body)` | 请求体 SHA256 十六进制；空 body 用 `sha256(b"")` 固定值 |
| `on_behalf_of` | `X-AIHub-On-Behalf-Of` 头的值，无该头则空串 |

签名 = `v1=` + HMAC-SHA256(共享密钥, 签名串) 的十六进制。

**要点**：
- 签名覆盖 on_behalf_of：第三方无法伪造用户维度请求
- 无 nonce：同一时间戳+签名的请求在 300 秒窗口内可重放（identity 为只读拉取，风险可接受；AI Hub 侧重试时用原签名头原样重发即可，无需重签）
- 签名头必须 ASCII；`hmac.compare_digest` 前已做 isascii 校验

## 端点详情

### GET /integration/identity — 拉取用户 AI 身份

```
GET /api/v1/integration/identity
X-AIHub-Timestamp: 1780000000
X-AIHub-Signature: v1=a3f5...
X-AIHub-On-Behalf-Of: 6650a1b2c3d4e5f6
```

成功（200），`data` 为三组 key（该用户可用的全部身份）：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "personal":    [ { "...": "个人主 key + 个人场景 key" } ],
    "department":  [ { "...": "所属部门 key（部门主/场景）" } ],
    "project":     [ { "...": "所属项目 key（项目主/场景）" } ]
  }
}
```

每个 key 对象的常用字段：

| 字段 | 说明 |
|------|------|
| `litellm_key_id` | **可用的 key 明文**（`sk-` 开头），调 LiteLLM 时作 Bearer/Authorization |
| `key_type` | `personal_main` / `personal_scene` / `dept_main` / `dept_scene` / `project_main` / `project_scene` |
| `is_active` | 是否启用，false 的 key 不可用 |
| `models` / `mcps` / `skills` / `agents` | 该 key 绑定可用的资源 id 列表 |
| `budget_*` / `tpm_limit` / `rpm_limit` | 预算与限流信息 |
| `expires_at` | key 过期时间（null 表示不过期） |

失败（统一格式 `{"code", "message", "data": null}`）：

| code | message | 含义 |
|------|---------|------|
| 401 | 签名无效 / 请求已过期 / 缺少有效时间戳 / 集成通道未启用 | 验签失败（细分原因只在 AIHelms 日志） |
| 400 | 缺少 X-AIHub-On-Behalf-Of 头 | identity 必须用户维度，服务身份（无 on_behalf_of）调用被拒 |
| 401 | 用户已禁用 | On-Behalf-Of 对应用户在 AIHelms 被禁用 |

> **重要**：用户实际使用 key 时，由最终客户端拿 `litellm_key_id` 调 LiteLLM 调用地址（见环境信息表），与 AIHelms API 无关。Key 启停/预算/限流均在 AIHelms/LiteLLM 层生效，AI Hub 只是分发通道——吊销在 AIHelms 一按即停。

## 代码骨架

### Python（httpx）

```python
import hashlib, hmac, time, httpx

SHARED_SECRET = "sk-conn-..."                # 与 AIHelms 配置一致
AIHELMS_BASE = "http://131.131.2.10:30700/api/v1"

def _signed_headers(method: str, path_with_query: str, body: bytes = b"",
                    on_behalf_of: str | None = None) -> dict[str, str]:
    ts = str(int(time.time()))
    message = "\n".join([
        "v1", ts, method.upper(), path_with_query,
        hashlib.sha256(body).hexdigest(), on_behalf_of or "",
    ]).encode()
    return {
        "X-AIHub-Timestamp": ts,
        "X-AIHub-Signature": "v1=" + hmac.new(
            SHARED_SECRET.encode(), message, hashlib.sha256).hexdigest(),
        "X-AIHub-On-Behalf-Of": on_behalf_of or "",
    }

def fetch_identity(aihub_user_id: str) -> dict:
    path = "/integration/identity"
    resp = httpx.get(
        f"{AIHELMS_BASE}{path}",
        headers=_signed_headers("GET", path, b"", aihub_user_id),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"]
```

### Node（fetch + crypto）

```js
const crypto = require("crypto");

const SHARED_SECRET = "sk-conn-...";           // 与 AIHelms 配置一致
const AIHELMS_BASE = "http://131.131.2.10:30700/api/v1";

function signedHeaders(method, pathWithQuery, body = Buffer.alloc(0),
                       onBehalfOf = "") {
  const ts = String(Math.floor(Date.now() / 1000));
  const message = ["v1", ts, method.toUpperCase(), pathWithQuery,
    crypto.createHash("sha256").update(body).digest("hex"), onBehalfOf,
  ].join("\n");
  const sig = "v1=" + crypto.createHmac("sha256", SHARED_SECRET)
    .update(message).digest("hex");
  return {
    "X-AIHub-Timestamp": ts,
    "X-AIHub-Signature": sig,
    "X-AIHub-On-Behalf-Of": onBehalfOf,
  };
}

async function fetchIdentity(aihubUserId) {
  const resp = await fetch(`${AIHELMS_BASE}/integration/identity`, {
    headers: signedHeaders("GET", "/integration/identity", Buffer.alloc(0),
                           aihubUserId),
  });
  return (await resp.json()).data;
}
```

## 联调自验 checklist

拿到共享密钥后按序自验，三步全过 = 通道可用：

```bash
BASE=http://131.131.2.10:30700/api/v1
SECRET=sk-conn-...
UID=<要拉取的用户在 AI Hub 的真实 user_id>

# ① 生成三头（签名串 = v1\n$TS\nGET\n/integration/identity\nsha256(b"")\n$UID）
read -r TS SIG <<< $(python3 -c "
import hashlib, hmac, time, os
ts = str(int(time.time()))
msg = '\n'.join(['v1', ts, 'GET', '/integration/identity',
                 hashlib.sha256(b'').hexdigest(), os.environ['UID']]).encode()
sig = 'v1=' + hmac.new(b'$SECRET', msg, hashlib.sha256).hexdigest()
print(ts, sig)")

# ② 拉身份 —— 期望 data 含 personal/department/project 三组
curl -s "$BASE/integration/identity" \
  -H "X-AIHub-Timestamp: $TS" \
  -H "X-AIHub-Signature: $SIG" \
  -H "X-AIHub-On-Behalf-Of: $UID"

# ③ 错签自查 —— 改动任一字段后应 401「签名无效」
curl -s "$BASE/integration/identity" \
  -H "X-AIHub-Timestamp: $TS" \
  -H "X-AIHub-Signature: v1=deadbeef" \
  -H "X-AIHub-On-Behalf-Of: $UID"
```

> ② 401 = 签名/时间戳问题，查下文排查决策树；401「集成通道未启用」= AIHelms 侧 `AIHUB_INTEGRATION_HMAC_SECRET` 未配置，找其运维。
> 用真实 user_id（AI Hub 里已存在的用户）：AIHelms 会为首次出现的 id 自动建档（占位档案，该用户首次 SSO 登录 AIHelms 时补全），自验时别用编造 id 往生产灌脏数据。

## 错误排查决策树

**401「签名无效」按序自查：**

1. **时钟**：两台服务器 NTP 是否同步，偏差须 ≤ 300 秒
2. **密钥一致**：AI Hub 侧密钥与 AIHelms `AIHUB_INTEGRATION_HMAC_SECRET` 是否同一个（含前后空格）
3. **签名串构造**：六个字段是否按 `\n` 连接、METHOD 大写、`path_with_query` 是否含 query、空 body 是否用 `sha256(b"")`
4. **query 编码**：query 必须保持原始编码（不要先解码再拼签名）
5. **on_behalf_of**：签名末字段须与 `X-AIHub-On-Behalf-Of` 头完全一致（无头时空串）
6. 还不行 → 联系 AIHelms 运维查日志（日志含拒绝路径）

**401「请求已过期」**：时钟偏差超 300 秒，校时后重试。
**401「集成通道未启用」**：AIHelms 侧密钥未配置。
**400「缺少 X-AIHub-On-Behalf-Of 头」**：拉用户身份必须带头。

## 密钥轮换

对称密钥无法并存验证（单密钥比对），轮换 = 双方协调同切，存在短暂不可用窗口（分钟级）：

1. AI Hub 应用管理重新生成（或协商生成）新密钥
2. 双方约定切换时刻，各自配置新密钥并重启
3. 失败请求按重试处理即可

疑似泄露应急：立即换密钥，期间旧密钥请求一律 401。

### 安全红线

- **共享密钥保管**：两侧均只存后端（密钥管理器/受控文件），不进代码仓库、不进前端、不落日志、不进群聊
- **密钥泄露面比非对称大**：任一侧泄露即全失守，须立即轮换
- **身份数据是敏感数据**：拉到的 `litellm_key_id` 是明文可用 key，AI Hub 侧按密钥同级保管，不落前端代码/日志，泄露立即联系 AIHelms 作废重发