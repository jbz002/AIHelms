---
name: aihub-integration
description: AI Hub 服务间集成对接指南。AI Hub 后端用 RS256 私钥签 JWT 断言（RFC 7523 JWT Bearer Assertion Grant）换取 AIHelms 短期集成令牌，拉取用户的 AI 身份（主 key、场景 key、绑定资源）。当用户需要"登录 AI Hub 后自动获取该用户在 AIHelms 的 AI key"、开发 AIHub→AIHelms 服务间身份供给、排查断言/token 报错、办理密钥转交或轮换时使用此 skill。
---

# AIHelms 服务间集成对接（JWT 断言换令牌）

## 适用场景

用户登录 AI Hub 后，AI Hub 的应用（如员工 ai chat）需要拿到该用户在 AIHelms 的 AI 身份（key 等），用于绑定个人模型调用。本通道提供"登录即拉取"的自动供给，**无需用户手动复制 key，也不使用长期 API Key**。

## 环境信息

| 环境 | AIHelms API 地址 | LiteLLM 调用地址（key 的实际使用端点） | 集成通道状态 |
|------|-----------------|--------------------------------------|-------------|
| 公司内网（生产） | `http://131.131.2.10:30700/api/v1` | `http://131.131.2.10:30710/v1` | ✅ 已开通，可直接联调 |
| 本地开发（联调） | `http://localhost/api/v1` | `http://localhost:4000/v1` | 按本地 `.env` 配置 |

> 端点全 URL = 上表地址 + 下文路径，如 `http://131.131.2.10:30700/api/v1/integration/token`。

## 整体流程

```
用户登录 AI Hub
   │
   ▼
AI Hub 后端：用 RSA 私钥签 JWT 断言
   sub=用户在 AI Hub 的 user_id, iss=aihub, aud=aihelms,
   jti=唯一串, iat/exp=签发/过期时间（寿命 ≤ 300 秒）
   │
   ▼
POST /integration/token {"assertion": "<JWT>"}
   │  AIHelms 验签 + 校验 claims + jti 防重放
   │  （用户首次出现时自动建档并开通个人主 key）
   ▼
返回 30 分钟集成访问令牌（access_token）
   │
   ▼
GET /integration/identity   Authorization: Bearer <access_token>
   │
   ▼
返回该用户全量 AI 身份：personal / department / project 三组 key
   │
   ▼
AI Hub 缓存令牌与身份，给下游应用绑定 key；
用户实际调模型 = 拿 key 打 LiteLLM 调用地址
```

## 准备工作

### 1. 拿到私钥（两种来源，按交接阶段）

**阶段 A —— 使用 AIHelms 代生成的转交件（当前联调期）**

AIHelms 侧已生成密钥对并在生产登记了公钥，转交给 AI Hub 的交付物：

| 文件 | 说明 |
|------|------|
| `aihub-integration.key` | RSA 私钥（2048），签断言用，**仅存 AI Hub 后端** |
| `aihelms-对接参数` | 即下文「AI Hub 侧配置清单」的值 |

拿到后先跑「联调自验」，通了即可开发。转交通过私密渠道（内网共享/加密压缩/密码另途），**不走群聊/邮件明文附件**。

**阶段 B —— 换成 AI Hub 自持有的密钥对（终态，推荐）**

代生成的私钥毕竟经手了 AIHelms 侧，正式运行期应换成 AI Hub 自己生成、私钥从未离开 AI Hub 的密钥对：

```bash
# 2048 位 RSA，在 AI Hub 服务器上生成，私钥永不外传
openssl genrsa -out aihub-integration.key 2048
openssl rsa -in aihub-integration.key -pubout -out aihub-integration.pub
```

新公钥（`-----BEGIN PUBLIC KEY-----` 格式，SubjectPublicKeyInfo）交 AIHelms 运维，按「密钥交接与轮换」流程无缝切换。

### 2. AI Hub 侧配置清单

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 私钥路径 | 上述 `.key` 文件 | 环境变量/密钥管理器均可 |
| AIHelms base_url | 见环境信息表 | 按部署环境切换 |
| iss | `aihub` | 固定值，与 AIHelms 登记一致 |
| aud | `aihelms` | 固定值，与 AIHelms 登记一致 |
| 令牌缓存 | 29 分钟内复用 | 到期前 1 分钟换新，勿每请求都打 token 端点（有每 IP 限速） |

## 断言规范

RS256 签名的 JWT，claims 契约：

| claim | 必填 | 规则 |
|-------|------|------|
| `sub` | 是 | 用户在 AI Hub 的 user_id（字符串）。AIHelms 按此映射本地用户 |
| `iss` | 是 | 固定 `aihub` |
| `aud` | 是 | 固定 `aihelms` |
| `jti` | 是 | 全局唯一串（如 uuid4）。**一次性**：同一 jti 二次验证即判重放拒绝 |
| `iat` | 是 | 签发时间（Unix 秒），与 AIHelms 服务器时钟偏差 ≤ 60 秒 |
| `exp` | 是 | 过期时间（Unix 秒），且 `exp - iat ≤ 300` 秒 |

最小合法断言 payload 示例：

```json
{
  "iss": "aihub",
  "aud": "aihelms",
  "sub": "6650a1b2c3d4e5f6",
  "jti": "5f8e9c2a-1b3d-4e5f-a6b7-c8d9e0f1a2b3",
  "iat": 1780000000,
  "exp": 1780000120
}
```

## 端点详情

### POST /integration/token — 断言换令牌

请求：

```json
POST /api/v1/integration/token
Content-Type: application/json

{ "assertion": "<RS256 签名的 JWT 字符串>" }
```

成功（200）：

```json
{
  "code": 200,
  "message": "集成访问令牌签发成功",
  "data": {
    "access_token": "eyJhbGciOi...",
    "token_type": "Bearer",
    "expires_in": 1800
  }
}
```

失败（统一格式 `{"code", "message", "data": null}`）：

| code | message | 含义 |
|------|---------|------|
| 401 | 断言无效或已过期 | 签名/iss/aud/exp/iat/sub/jti 任一不符，或 jti 重放（细分原因只在 AIHelms 日志） |
| 403 | 集成通道未启用 | AIHelms 侧未开启集成，联系其运维 |
| 403 | 请求过于频繁，请稍后重试 | 超出每 IP 每分钟限速，检查令牌缓存是否生效 |

### GET /integration/identity — 拉取用户 AI 身份

```
GET /api/v1/integration/identity
Authorization: Bearer <access_token>
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

> **重要**：集成 access_token 只能调本端点。拿它调 AIHelms 其他接口一律 401（令牌按用途隔离）。用户实际使用 key 时，由最终客户端拿 `litellm_key_id` 调 LiteLLM 调用地址（见环境信息表），与 AIHelms API 无关。

## 代码骨架

### Python（httpx + PyJWT）

```python
import time, uuid, jwt, httpx

PRIVATE_KEY = open("aihub-integration.key").read()
AIHELMS_BASE = "http://131.131.2.10:30700/api/v1"

def _sign_assertion(aihub_user_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "aihub", "aud": "aihelms",
            "sub": aihub_user_id,          # AI Hub 侧 user_id
            "jti": str(uuid.uuid4()),      # 每次新生成，绝不能复用
            "iat": now, "exp": now + 120,
        },
        PRIVATE_KEY, algorithm="RS256",
    )

class AihelmsClient:
    """登录后调用 exchange_and_fetch；令牌缓存 29 分钟，到期自动换新。"""

    def __init__(self):
        self._token, self._token_exp = None, 0.0

    def _access_token(self, aihub_user_id: str) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        resp = httpx.post(
            f"{AIHELMS_BASE}/integration/token",
            json={"assertion": _sign_assertion(aihub_user_id)},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        self._token = data["access_token"]
        self._token_exp = time.time() + data["expires_in"]
        return self._token

    def fetch_identity(self, aihub_user_id: str) -> dict:
        resp = httpx.get(
            f"{AIHELMS_BASE}/integration/identity",
            headers={"Authorization": f"Bearer {self._access_token(aihub_user_id)}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["data"]
```

### Node（jsonwebtoken + fetch）

```js
const jwt = require("jsonwebtoken");
const fs = require("fs");

const PRIVATE_KEY = fs.readFileSync("aihub-integration.key");
const AIHELMS_BASE = "http://131.131.2.10:30700/api/v1";

function signAssertion(aihubUserId) {
  const now = Math.floor(Date.now() / 1000);
  return jwt.sign(
    {
      iss: "aihub", aud: "aihelms",
      sub: aihubUserId,           // AI Hub 侧 user_id
      jti: crypto.randomUUID(),  // 每次新生成
      iat: now, exp: now + 120,
    },
    PRIVATE_KEY,
    { algorithm: "RS256" }
  );
}

// 换令牌 + 拉身份（按 user_id 缓存令牌，结构与 Python 版一致）
async function fetchIdentity(aihubUserId, cachedToken) {
  const tokenResp = cachedToken
    ? { ok: true, json: async () => ({ data: { access_token: cachedToken, expires_in: 1800 } }) }
    : await fetch(`${AIHELMS_BASE}/integration/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assertion: signAssertion(aihubUserId) }),
      });
  const tokenData = (await tokenResp.json()).data;
  const resp = await fetch(`${AIHELMS_BASE}/integration/identity`, {
    headers: { Authorization: `Bearer ${tokenData.access_token}` },
  });
  return (await resp.json()).data;
}
```

## 联调自验 checklist

拿到私钥后按序自验，四步全过 = 通道可用：

```bash
BASE=http://131.131.2.10:30700/api/v1
KEY=/path/to/aihub-integration.key

# ① 签断言（sub 换成要拉取的用户在 AI Hub 的真实 user_id）
ASSERTION=$(python3 -c "
import time, uuid, jwt
now = int(time.time())
print(jwt.encode({'iss':'aihub','aud':'aihelms','sub':'<aihub_user_id>',
                  'jti':str(uuid.uuid4()),'iat':now,'exp':now+120},
                 open('$KEY').read(), algorithm='RS256'))")

# ② 换令牌 —— 期望 {"code":200,"message":"集成访问令牌签发成功",...}
curl -s -X POST $BASE/integration/token \
  -H "Content-Type: application/json" -d "{\"assertion\":\"$ASSERTION\"}"

# ③ 拉身份 —— 期望 data 含 personal/department/project 三组
TOKEN=<上一步 data.access_token>
curl -s $BASE/integration/identity -H "Authorization: Bearer $TOKEN"

# ④ 隔离确认（可选）—— 集成令牌调普通接口应 401「token 无效」
curl -s $BASE/ai-keys/my -H "Authorization: Bearer $TOKEN"
```

> ② 401 = 断言问题，查下文排查决策树；403「集成通道未启用」= AIHelms 侧配置问题，找其运维。
> ③ 用真实 user_id（AI Hub 里已存在的用户）：AIHelms 会为首次出现的 sub 自动建档（占位档案，该用户首次 SSO 登录 AIHelms 时补全），自验时别用编造 id 往生产灌脏数据。

## 错误排查决策树

**401「断言无效或已过期」按序自查：**

1. **时钟**：两台服务器 NTP 是否同步，偏差须 ≤ 60 秒（iat 容差）
2. **iss/aud 拼写**：必须是 `aihub` / `aihelms`，大小写敏感
3. **密钥配对**：AI Hub 私钥是否对应 AIHelms 登记的公钥（换了私钥要先走轮换流程）
4. **jti 重复**：断言是否被重发（重试逻辑复用了旧断言）。jti 每次必须新生成
5. **exp 超限**：`exp - iat` 是否 ≤ 300 秒
6. 还不行 → 联系 AIHelms 运维查日志（日志含具体拒绝原因）

**403「集成通道未启用」**：AIHelms 侧开关未开或公钥未配置。
**403「请求过于频繁」**：超出每 IP 每分钟限速（默认 60）。检查令牌缓存 — 令牌 30 分钟有效，不应频繁换新。

## 密钥交接与轮换

### 首次交接（AIHelms → AI Hub）

1. AIHelms 通过私密渠道交付私钥文件（当前为代生成的 `aihub-integration.key`，对应公钥已登记生产）
2. AI Hub 按上文 checklist 联调自验通过 → 进入开发
3. 转交的私钥在 AI Hub 侧落位到密钥管理器/受控文件后，**本地临时拷贝（聊天记录/下载目录/邮件附件）即刻删除**

### 换成自持有密钥（阶段 B，正式运行前）

1. AI Hub 生成自己的密钥对（见准备工作），新公钥交 AIHelms 运维
2. AIHelms 将新公钥**追加**进配置（支持多把公钥并存，旧公钥此时仍有效）
3. AI Hub 切换到新私钥签发（新断言立即走新钥验证，旧断言在有效期内仍可过）
4. 观察 1-2 天无 401 异常 → AIHelms 删除旧公钥，交接完成

### 日常轮换（定期/疑似泄露）

同一流程：追加新公钥 → 切私钥 → 删旧公钥。泄露应急时跳过观察期直接删旧。轮换期间**无需停机**，双方按序操作即可。

### 安全红线

- **私钥保管**：只存 AI Hub 后端（密钥管理器/受控文件），不进代码仓库、不进前端、不落日志、不进群聊
- **断言勿落日志**：断言含用户身份且有效期短（≤300s），泄露可被立即重放
- **每次断言新 jti**：实现层面禁止断言缓存复用（重试时重新签发，不重发旧串）
- **身份数据是敏感数据**：拉到的 `litellm_key_id` 是明文可用 key，AI Hub 侧按密钥同级保管，不落前端代码/日志，泄露立即联系 AIHelms 作废重发
