# BUG：删除/编辑模型部署时 LiteLLM 侧残留孤儿 deployment

## 现象

删除 aihelms 模型（或反复编辑/改名/禁用部署）后，LiteLLM `LiteLLM_ProxyModelTable` 残留 aihelms 已不追踪的 deployment 记录（下称「孤儿」）。

本次复现：删除整个 `deepseek-v4-flash` 模型（4 个 deployment 全删），litellm 仍残留 5 条孤儿：

| model_name | litellm mid | active |
|---|---|---|
| `deepseek-v4-flash-0731(Anthropic)` | e8ac964b / 610115c5 | false |
| `deepseek-v4-flash-0732` | 0516d86a | false |
| `deepseek-v4-flash-0732(Anthropic)` | ea9cb9f8 / 05fb6854 | false |

而 aihelms 侧 `models` / `model_deployments` 均已 0 行，`ai_keys.models` 无 deepseek 引用——只有 litellm 单边残留。

## 影响

1. **路由池污染（最严重）**：孤儿若 `active=true` 会混入路由池。本次排查的起因正是——`deepseek-v4-flash-0731` group 实际挂了 4 个 deployment（含 aihelms 已删的孤儿），`simple-shuffle` 等权随机，使配好的 8:1 权重失效，打成 50:50。
2. `/v1/models` 列出冗余/已废弃模型，客户端可命中。
3. LiteLLM DB 无限膨胀。
4. 同名 deployment 累积，干扰按 model_name 的诊断与统计。

## 根因

aihelms ↔ litellm 的 deployment 同步是**单向追踪、单 id 记录**：

- aihelms `model_deployments.litellm_model_id` 只保存每个 deployment **最新一次** sync 产生的 litellm uuid。
- 任何会「在 litellm 侧产生新记录」的操作（re-sync 新建、改名、禁用切换、版本升级遗留），其**旧记录 aihelms 不再追踪**。
- 删除/改名时，只按当前 `litellm_model_id` 操作 litellm，够不到历史残留。

三个代码路径共同造成累积：

| 位置 | 行为 | 漏洞 |
|---|---|---|
| `model_service.py:607` `update_deployment` | `litellm_model_id` 为空且 `is_active` → `_sync_deployment_to_litellm` → `add_model` **新建** | 若 `litellm_model_id` 曾因故被置空，新建后旧 litellm 记录残留 |
| `model_service.py:253` `_sync_model_rename` | 改名时 `update_model` 只改**当前追踪 id** 的 model_name | litellm 里旧 model_name 的历史记录不被更新/清理 |
| `model_service.py:374` `delete_model` | 遍历 deployments，按 `d.litellm_model_id` 调 `/model/delete` | 只删当前追踪的 id，孤儿（aihelms 已丢关联的）残留 |

`_get_litellm_model_name`（`model_service.py:874`）禁用时会加 `__disabled__` 后缀——但本次孤儿 model_name 是 `-0731/-0732`（旧日期）**无 `__disabled__` 后缀**，证明它们不是当前禁用逻辑产生，而是 **model_id 还带日期时的历史 sync 记录**，改名后没清。

## 本次触发链（deepseek-v4-flash）

1. model_id 早期带日期后缀（`-0731` / `-0732`，多版本实验期）。
2. 反复编辑部署（改 weight、active、credential）触发多次 re-sync。
3. 某次 re-sync 走 `add_model` 新建 litellm 记录，旧记录残留。
4. 改名 model_id → `deepseek-v4-flash`（去日期），`_sync_model_rename` 只 update 当前追踪 id 的 model_name。
5. 取消发布/禁用产生 `active=false` 记录，model_name 保留旧日期名。
6. 删除模型：`delete_model` 只清 4 个当前 deployment 关联的 litellm_model_id，5 个历史孤儿残留。

## 修复方案

### 短期：一次性清理（本次已执行）

判据：litellm deployment 的 `model_id`（litellm uuid）不在 aihelms `model_deployments.litellm_model_id` 集合内 = 孤儿。

清理动作（用 litellm API，让 router 缓存即时更新，勿裸 SQL）：

```bash
MK=$(docker exec aihelms-litellm printenv LITELLM_MASTER_KEY)
# 取孤儿 uuid（aihelms 已无对应 deployment 的 litellm 记录）
for mid in <orphan_uuid_1> <orphan_uuid_2> ...; do
  curl -s -X POST http://127.0.0.1:30711/model/delete \
    -H "Authorization: Bearer $MK" -H "Content-Type: application/json" \
    -d "{\"id\":\"$mid\"}"
done
```

本次已清 5 条，验证：

```sql
SELECT count(*) FROM "LiteLLM_ProxyModelTable" WHERE model_name LIKE '%deepseek-v4-flash%';  -- = 0
```

### 根治：反向对账清理任务（推荐）

新增定时任务（或挂到 `delete_model` / 各 sync 收尾），做 litellm → aihelms 反向对账：

1. 拉 litellm `/model/info` 全量 deployment → 得 litellm uuid 集合 **L**。
2. 查 aihelms `SELECT litellm_model_id FROM model_deployments WHERE litellm_model_id IS NOT NULL` → 集合 **A**。
3. 差集 **L − A** = 孤儿。
4. 逐个调 litellm `/model/delete`。

优点：不依赖知道历史 model_id / 后缀变体，通用兜底；能清掉所有过去累积与未来漏网。

建议放 Celery 定时（如每日）+ `delete_model` 末尾立即跑一次。

### 加固：减少孤儿产生

- `update_deployment` 走 `add_model` 新建前（607 分支），先按当前 `_get_litellm_model_name` 查 litellm 同名旧记录并删除，避免同 group 重复累积。
- `_sync_model_rename` 改名时，除 update 当前 deployments，额外清理 litellm 里所有 `model_name = 旧名` 及其变体（`(Anthropic)` / `__disabled__`）的残留。
- `delete_model` 删完当前 deployments 后，按该模型历史可能用过的 model_name 前缀扫 litellm 兜底清一遍。

## 验证清单

- [x] litellm `LiteLLM_ProxyModelTable` deepseek 残留 = 0
- [x] aihelms `models` / `model_deployments` = 0
- [x] `ai_keys.models` 无 deepseek 引用
- [ ] 反向对账任务落地后，再次删模型验证无残留（待开发）

## 相关文件

- `apps/services/model_service.py` — `delete_model`(374) / `update_deployment`(525) / `_sync_model_rename`(253) / `_sync_deployment_to_litellm`(977) / `_get_litellm_model_name`(874)
- `apps/services/litellm_client.py` — `add_model`(299) / `update_model`(317) / `delete_model`(313)
