---
name: aihub-integration
description: AI Hub 服务间集成对接指南（方式七自省验证）。子应用持 AI Hub 签发凭证（用户 access_token）直连调 AIHelms /integration/identity，AIHelms 透传凭证向 AI Hub /auth/introspect 验证后返回该用户 AI 身份（主 key、场景 key）。当用户需要"登录 AI Hub 后自动获取该用户在 AIHelms 的 AI key"、开发 AIHub→AIHelms 身份供给、排查 identity 401/403、了解凭证续期时使用此 skill。
---

# AIHelms 服务间集成对接（方式七：自省验证）

## 适用场景

用户登录 AI Hub 后，AI Hub 侧应用（如员工 ai chat）需要拿到该用户在 AIHelms 的 AI 身份（key 等），用于绑定个人模型调用。本通道提供"登录即拉取"的自动供给，**无需用户手动复制 key**。

鉴权采用「直连 + 自省」：调用方持 **AI Hub 签发的凭证**（用户 access_token），AIHelms 收到后原样转发给 AI Hub 验证，凭 AI Hub 返回的调用方身份放行。**无共享密钥、无私有令牌、验证与授权全部由 AI Hub 集中完成**。

> 历史方案：方式六 HMAC 验签（共享密钥）已废弃 — AI Hub 方确认「API 连接」走代理方式将删除，改走本方式。

## 环境信息

| 环境 | AIHelms API 地址 | AI Hub 地址 | LiteLLM 调用地址（key 的实际使用端点） |
|------|-----------------|-------------|--------------------------------------|
| 公司内网（生产） | `http://131.131.2.10:30700/api/v1` | `http://131.131.2.10:30080` | `http://131.131.2.10:30710/v1` |
| 本地开发（联调） | `http://localhost/api/v1` | `http://111.229.103.94:30080` | `http://localhost:4000/v1` |

> AIHelms 侧所需配置：`AI_HUB_URL` + `AI_HUB_APP_CODE=aihelms`（SSO 已有，无新增配置）。

## 整体流程

```
用户登录 AI Hub
   │
   ▼
AI Hub 侧应用（B）拿到该用户的 access_token
（OAuth2 /token 换取，30 分钟过期，按「无感续期」刷新）
   │
   ▼
GET /api/v1/integration/identity        ← 直连 AIHelms
Authorization: Bearer <access_token>
   │
   ▼
AIHelms（A）：把 Bearer 原样转发 AI Hub 自省
GET {AI_HUB_URL}/api/v1/auth/introspect?app_code=aihelms&target_path=/api/v1/integration/identity&method=GET
   │  AI Hub 验证凭证 + 应用间授权 + 落调用日志
   ▼
200 {valid, caller_type:"user", user_id, app_roles}
   │  AIHelms 按 user_id（= AI Hub 用户 ID）定位本地用户
   │  首次出现自动建档并开通个人主 key
   ▼
返回该用户全量 AI 身份：personal / department / project 三组 key
   │
   ▼
AI Hub 侧缓存身份，给下游应用绑定 key；
用户实际调模型 = 拿 key 打 LiteLLM 调用地址
```

## 端点详情

### GET /integration/identity — 拉取用户 AI 身份

```
GET /api/v1/integration/identity
Authorization: Bearer <用户的 AI Hub access_token>
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
| 401 | 缺少 AI Hub 凭证 | 未带 Bearer 头 |
| 401 | 凭证无效或无权限 | AI Hub 自省不通过（token 过期/无效/应用未授权） |
| 401 | 凭证验证服务不可用 | AI Hub 不可达（fail-closed） |
| 403 | 个人数据需用户凭证 | 用了应用服务态凭证（AppAPIKey）调个人接口 |
| 401 | 用户已禁用 | 凭证对应的用户在 AIHelms 被禁用 |

> **重要**：用户实际使用 key 时，由最终客户端拿 `litellm_key_id` 调 LiteLLM 调用地址（见环境信息表），与 AIHelms API 无关。Key 启停/预算/限流均在 AIHelms/LiteLLM 层生效，AI Hub 只是分发通道——吊销在 AIHelms 一按即停。

## 调用方代码骨架（AI Hub 侧应用）

```python
import httpx

AIHELMS_BASE = "http://131.131.2.10:30700/api/v1"

def fetch_identity(user_access_token: str) -> dict:
    """user_access_token: 该用户登录 AI Hub 后签发的 access_token（30min，注意续期）。"""
    resp = httpx.get(
        f"{AIHELMS_BASE}/integration/identity",
        headers={"Authorization": f"Bearer {user_access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"]
```

要点：
- **凭证是用户维度**：必须用用户 access_token（`caller_type=user`）。用应用 AppAPIKey 调会被 403 拒（个人数据防服务态查任意用户）
- **access_token 30 分钟过期**：调用方按 AI Hub「无感续期」机制刷新；过期后 identity 返回 401，刷新后重试即可
- identity 结果可按用户短 TTL 缓存（如 5 分钟），key 变更频率低

## 联调自验 checklist

```bash
# ① 拿一个真实用户的 AI Hub access_token（OAuth2 /token 换取，或登录接口返回）
TOKEN=<access_token>

# ② 拉身份 —— 期望 200，data 含 personal/department/project 三组
curl -s "http://131.131.2.10:30700/api/v1/integration/identity" \
  -H "Authorization: Bearer $TOKEN"

# ③ 错凭证自查 —— 期望 401「凭证无效或无权限」
curl -s "http://131.131.2.10:30700/api/v1/integration/identity" \
  -H "Authorization: Bearer garbage"
```

> ② 401「凭证验证服务不可用」= AIHelms 到 AI Hub 网络不通，找 AIHelms 运维。
> 401「凭证无效」多为 token 过期（30min）或跨实例 token（测试服/生产 AI Hub 不互认）。

## 错误排查决策树

**401「凭证无效或无权限」按序自查：**
1. token 是否过期（30 分钟）— 重新获取或续期
2. token 是否与 AI Hub 实例匹配 — 测试服（111.229.103.94）与生产（131.131.2.10）token 不互认
3. AI Hub introspect 403「该应用未被授权调用目标应用」— 调用方应用需在 AI Hub「应用管理 → 可调用的应用」勾选 aihelms
4. AI Hub introspect 403「无访问该应用的权限」— 用户不满足 aihelms 访问白名单

**403「个人数据需用户凭证」**：用了 AppAPIKey（应用服务态），改用用户 access_token。

## 安全红线

- **身份数据是敏感数据**：拉到的 `litellm_key_id` 是明文可用 key，AI Hub 侧按密钥同级保管，不落前端代码/日志，泄露立即联系 AIHelms 作废重发
- **凭证传递链**：用户 token 只在 AI Hub 侧应用后端与 AIHelms 之间流转，不透传给前端第三方
- AIHelms 侧每次 identity 拉取落管理员审计日志（不记 key 明文），AI Hub 侧每次 introspect 落调用日志，两侧可对账
