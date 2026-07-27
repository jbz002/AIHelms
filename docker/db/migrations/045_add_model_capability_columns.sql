-- 模型基本属性增强:上下文窗口 + 结构化能力位
-- 数据源为平台内置注册表快照(apps/data/model_registry.json),非 LiteLLM 实时
-- additive-only, idempotent
ALTER TABLE aihelms.models
    ADD COLUMN IF NOT EXISTS max_input_tokens INT,
    ADD COLUMN IF NOT EXISTS max_output_tokens INT,
    ADD COLUMN IF NOT EXISTS supports_vision BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS supports_function_calling BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS supports_reasoning BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS supports_response_schema BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS supports_parallel_function_calling BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS supports_tool_choice BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS litellm_provider VARCHAR(64) DEFAULT '',
    ADD COLUMN IF NOT EXISTS registry_synced_at TIMESTAMPTZ;
