-- 093: 日志口径三层分离——供应商身份 / 方言 / 路由前缀
-- 背景：llm_call_logs.model 同步自 LiteLLM SpendLogs.model，那是解析后的上游模型串
-- （openai/deepseek-v4.1-flash），带路由 handler 前缀；provider 同步自
-- custom_llm_provider（同为首缀值），导致日志里"供应商"恒显示 openai，真实供应商
-- （如 OpenCode）丢失。三层语义各自独立，不能混用：
--   供应商身份 → provider_id / provider_name
--   协议方言   → credential_info.format
--   路由前缀   → provider_prefix_map（实现细节，仅排障用）
-- 幂等：ADD COLUMN IF NOT EXISTS + 仅回填 NULL；重复执行 no-op。

ALTER TABLE aihelms.llm_call_logs
    ADD COLUMN IF NOT EXISTS model_group VARCHAR(128),
    ADD COLUMN IF NOT EXISTS provider_id BIGINT,
    ADD COLUMN IF NOT EXISTS provider_name VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_llm_logs_model_group ON aihelms.llm_call_logs(model_group);
CREATE INDEX IF NOT EXISTS idx_llm_logs_provider_name ON aihelms.llm_call_logs(provider_name);

-- 1) 模型组回填：LiteLLM 侧有 model_group 列时按 request_id 对齐
DO $$
BEGIN
    IF to_regclass('public."LiteLLM_SpendLogs"') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public'
             AND table_name = 'LiteLLM_SpendLogs'
             AND column_name = 'model_group'
       )
    THEN
        UPDATE aihelms.llm_call_logs l
        SET model_group = s.model_group
        FROM public."LiteLLM_SpendLogs" s
        WHERE s.request_id = l.request_id
          AND s.model_group IS NOT NULL
          AND s.model_group <> ''
          AND l.model_group IS NULL;
    END IF;
END $$;

-- 2) 供应商身份回填：部署 → 凭证 → 供应商
UPDATE aihelms.llm_call_logs l
SET provider_id = p.id,
    provider_name = p.name
FROM aihelms.model_deployments d
JOIN aihelms.credentials c ON c.id = d.credential_id
JOIN aihelms.providers p ON p.id = c.provider_id
WHERE l.deployment_id = d.id
  AND l.provider_name IS NULL;
