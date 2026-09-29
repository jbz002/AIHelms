---
name: aihub-integration
description: AI Helms 服务间集成对接指南（方式七自省验证）。两类调用方：其他子应用持 AI Hub 签发的用户 access_token 直连调 AIHelms /integration/identity 拉取该用户 AI 身份（LiteLLM key 明文 + 绑定的模型/MCP/Skill/Agent 资源）；AI Hub 平台自身（如个人资料页展示用户在本系统的 key）用用户代理 token 走同一端点。当用户需要"登录后自动获取该用户在 AIHelms 的 AI key"、开发 AIHub→AIHelms 身份供给、AI Hub 个人资料页展示 key、排查 identity 401/403、了解凭证续期时使用此 skill。
---

# AIHelms AI 身份集成对接（直连 + 自省验证）

## 适用场景

| 调用方 | 场景 | 凭证 |
|--------|------|------|
| 其他子应用（如ai-assistant） | 用户登录后自动拉取其在 AIHelms 的 AI 身份（key 等），绑定个人模型调用，无需用户手动复制 key | 该用户的 AI Hub access_token（OAuth2 `/token` 换取） |
| AI Hub 平台自身 | 个人资料页等处展示该用户在本系统的 key 与资源绑定 | 用户代理 token（或用户 access_token），见下文专节 |

鉴权采用「直连 + 自省」：调用方持 **AI Hub 签发的用户维度凭证**直连 AIHelms，AIHelms 把凭证原样转发给 AI Hub `/api/v1/auth/introspect` 验证，凭返回的调用方身份放行。无共享密钥，验证与授权（应用间授权、访问白名单、调用日志）全部由 AI Hub 集中完成。

## 环境信息

| 环境 | AIHelms API 地址 | LiteLLM 调用地址（key 的实际使用端点） |
|------|-----------------|--------------------------------------|
| 公司内网（生产） | `http://131.131.2.10:30700/api/v1` | `http://131.131.2.10:30710/v1` |

## 整体流程

```
用户登录 AI Hub
   │
   ▼
调用方（子应用或 AI Hub 平台自身）持有该用户的凭证
   │
   ▼
GET /api/v1/integration/identity        ← 直连 AIHelms
Authorization: Bearer <用户维度凭证>
   │
   ▼
AIHelms：把 Bearer 原样转发 AI Hub 自省
   │  AI Hub 验证凭证 + 应用间授权 + 落调用日志
   ▼
200 {valid, caller_type:"user", user_id, app_roles}
   │  AIHelms 按 user_id（= AI Hub 用户 ID）定位本地用户
   │  用户首次出现自动建档并开通个人主 key
   ▼
返回该用户全量 AI 身份：personal / department / project 三组 key
   │
   ▼
调用方缓存身份，绑定 key；
用户实际调模型 = 拿 key 打 LiteLLM 调用地址
```

## AI Hub 平台自身集成（个人资料页展示场景）

AI Hub 个人资料页要展示"该用户在 AIHelms 的 key"，走**同一端点** `/api/v1/integration/identity`，只是凭证来源不同：

| 凭证 | introspect 结果 | 能否调 identity | 说明 |
|------|----------------|----------------|------|
| **用户代理 token**（AI Hub 为当前登录用户签发的短时 JWT） | `caller_type=user` + `user_id` | ✅ 推荐 | AI Hub 是凭证签发方，服务端渲染资料页时现签现用，无续期问题 |
| 用户 access_token（AI Hub 登录态的） | `caller_type=user` + `user_id` | ✅ 可用 | 30 分钟过期，过期走 `/auth/refresh` 续期后重试 |
| 平台 API Key（AI Hub 服务身份） | `caller_type=app`，`app_code="ai-hub"` | ❌ 403 | 个人数据必须用户维度凭证，服务态一律拒（防查任意用户） |

要点：

- **用户对齐零成本**：introspect 返回的 `user_id` 就是 AI Hub 用户 ID，AIHelms 据此定位本地用户；用户从未进过 AIHelms 也没关系，首次拉取自动建档并开通个人主 key。
- **无需配置应用间授权**：AI Hub 自身登录签发的用户 token 无应用归属，introspect 跳过 `allowed_target_apps` 校验（子应用调用才需要在「应用管理 → 可调用的应用」勾选 aihelms）。
- **资料页渲染建议**：`personal` 组是本人 key（主 key + 场景 key），`department` / `project` 组是部门/项目共享 key，可分组展示；key 明文建议脱敏显示（`sk-****xxxx`）+ 点击复制/揭示。
- **每次拉取双侧落审计**，可对账。资料页属低频访问，直接拉即可；要缓存建议 TTL ≥ 5 分钟。

## 端点详情

### GET /integration/identity — 拉取用户 AI 身份

```
GET /api/v1/integration/identity
Authorization: Bearer <用户维度的 AI Hub 凭证>
```

成功（200），`data` 为三组 key（该用户可用的全部身份）：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "personal":    [ { "…": "个人主 key + 个人场景 key" } ],
    "department":  [ { "…": "所属部门 key（部门主/场景）" } ],
    "project":     [ { "…": "所属项目 key（项目主/场景）" } ]
  }
}
```

每个 key 对象的完整字段：

**key 本体**

| 字段 | 说明 |
|------|------|
| `id` | AIHelms 平台 key 记录 id（仅标识用，不是调 LiteLLM 的 key） |
| `litellm_key_id` | **可用的 key 明文**（`sk-` 开头），调 LiteLLM 时作 Bearer/Authorization。注意字段名带 `_id`，但值就是明文 key |
| `litellm_key_alias` | LiteLLM 侧别名（如 `user:zhangsan/main`） |
| `name` / `description` | key 的显示名与描述（展示用） |
| `key_type` | `personal_main` / `personal_scene` / `dept_main` / `dept_scene` / `project_main` / `project_scene` |
| `owner_type` / `owner_id` | 归属：`user` / `department` / `project` |
| `is_active` | 是否启用，false 的 key 不可用 |
| `tags` | 标签列表 |
| `scenario_id` | 场景 key 关联的业务场景 id（主 key 为 null） |

**资源绑定（该 key 下能用什么）**

| 字段 | 说明 |
|------|------|
| `models` | 可用**模型 id 字符串列表**（如 `["gpt-4o", "claude-sonnet-5"]`），即 LiteLLM 模型名，可直接展示、直接作 `model` 参数 |
| `skills` | 绑定的 Skill 平台内部 id 列表 |
| `mcps` | 绑定的 MCP Server 平台内部 id 列表 |
| `agents` | 绑定的智能体平台内部 id 列表 |

> **资源 id 说明**：`skills` / `mcps` / `agents` 返回的是 AIHelms 内部数字 id，跨系统无语义，仅用于判断"该 key 绑定了几个资源"；名称/图标级明细暂不随本接口提供。`models` 无此问题，直接展示。

**预算与限流**

| 字段 | 说明 |
|------|------|
| `budget_limit` / `budget_used` | 预算上限 / 已用（字符串十进制，平台内部结算价口径） |
| `budget_hard_limit` | 是否预算硬阻断（true 且用超即卡死 key） |
| `budget_duration` | 预算周期（`30d` 等） |
| `budget_scope` / `budget_models_total` / `budget_mcps_total` / `budget_models_per` / `budget_mcps_per` | 预算口径与分项额度 |
| `model_budgets` / `mcp_budgets` | 按模型 / 按 MCP 的分项预算映射 |
| `rate_limit_mode` / `tpm_limit` / `rpm_limit` / `max_parallel_requests` | 限流配置 |

**状态与时间**

| 字段 | 说明 |
|------|------|
| `expires_at` | key 过期时间（null 不过期） |
| `last_used_at` | 最近使用时间（可作"最近使用"展示） |
| `created_at` / `updated_at` | 创建 / 更新时间 |
| `created_by` | 创建人平台用户 id |

失败（统一格式 `{"code", "message", "data": null}`）：

| code | message | 含义 |
|------|---------|------|
| 401 | 缺少 AI Hub 凭证 | 未带 Bearer 头 |
| 401 | 凭证无效或无权限 | AI Hub 自省不通过（token 过期/无效/应用未授权） |
| 401 | 凭证验证服务不可用 | AI Hub 不可达（fail-closed） |
| 403 | 个人数据需用户凭证 | 用了服务态凭证（AppAPIKey / 平台 API Key）调个人接口 |
| 401 | 用户已禁用 | 凭证对应的用户在 AIHelms 被禁用 |

> **key 的实际使用**：最终客户端拿 `litellm_key_id` 调 LiteLLM 调用地址（见环境信息表），与 AIHelms API 无关。key 启停/预算/限流均在 AIHelms/LiteLLM 层生效——吊销在 AIHelms 一按即停。

## 调用方代码骨架

```python
import httpx

AIHELMS_BASE = "http://131.131.2.10:30700/api/v1"

def fetch_identity(user_token: str) -> dict:
    """user_token: 用户维度的 AI Hub 凭证
    （子应用：OAuth2 /token 换取的 access_token；AI Hub 自身：用户代理 token）"""
    resp = httpx.get(
        f"{AIHELMS_BASE}/integration/identity",
        headers={"Authorization": f"Bearer {user_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"]
```

要点：
- **凭证必须是用户维度**（`caller_type=user`），服务态凭证一律 403
- 子应用用的用户 access_token 30 分钟过期，按 AI Hub「无感续期」机制刷新；过期后 identity 返回 401，刷新重试即可
- 拉到的 `litellm_key_id` 是明文可用 key，按密钥同级保管，不落日志
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

> ② 401「凭证验证服务不可用」= AIHelms 到 AI Hub 网络不通，联系 AIHelms 侧排查。
> 401「凭证无效」多为 token 过期（30min）或跨实例 token（测试服/生产 AI Hub 不互认）。

## 错误排查决策树

**401「凭证无效或无权限」按序自查：**
1. token 是否过期（30 分钟）— 重新获取或续期
2. token 是否与 AI Hub 实例匹配 — 测试服与生产 AI Hub 的 token 不互认
3. AI Hub introspect 403「该应用未被授权调用目标应用」— 调用方子应用需在 AI Hub「应用管理 → 可调用的应用」勾选 aihelms（AI Hub 自身签发的用户 token 无此检查）
4. AI Hub introspect 403「无访问该应用的权限」— 用户不满足 aihelms 访问白名单（`required_permissions`）

**403「个人数据需用户凭证」**：用了服务态凭证（AppAPIKey / 平台 API Key），改用用户维度凭证。
