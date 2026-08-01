-- 060: llm_call_logs 增加 is_platform_call 列，标记走 LITELLM_MASTER_KEY 的平台运维调用。
-- 平台默认模型调用（文档接口提取 / Skill 安全审查复核 / 模型连通性测试）经 platform_llm
-- 统一用 master key，同步任务无法将其归因到具体人或 Key；前端据此渲染「平台系统」。
-- 仅新同步行打标；历史行未存原始 api_key token，不回填。
-- 幂等：IF NOT EXISTS；附加式，不动既有列。

ALTER TABLE aihelms.llm_call_logs
    ADD COLUMN IF NOT EXISTS is_platform_call BOOLEAN DEFAULT false;
