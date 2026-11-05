-- 092: 凭证方言词汇收敛——credential_info.format 只保留 openai / anthropic 两种协议方言。
-- lmstudio / ollama 是供应商不是方言，归一为 openai（Ollama 官方 /v1 即 OpenAI 方言端点；
-- 对齐 cc-switch apiFormat 与 providerType/category 的概念分离）。
-- 同步归一 provider.config.supported_formats。幂等：归一后再跑 no-op。
-- 注意：format=ollama 的存量凭证归一后路由前缀覆盖表命中 (ollama,openai,chat)→openai，
-- 与原 (ollama,ollama,chat)→ollama 不同；涉及部署需在管理端重新同步一次以对齐部署串。

UPDATE aihelms.credentials
SET credential_info = credential_info
    || jsonb_build_object('format', 'openai')
    || jsonb_build_object('custom_llm_provider', 'openai')
WHERE credential_info->>'format' IN ('lmstudio', 'ollama');

UPDATE aihelms.providers
SET config = jsonb_set(
    config,
    '{supported_formats}',
    (
        SELECT COALESCE(
            jsonb_agg(DISTINCT CASE WHEN elem IN ('lmstudio', 'ollama') THEN 'openai' ELSE elem END),
            '[]'::jsonb
        )
        FROM jsonb_array_elements_text(config->'supported_formats') AS elem
    )
)
WHERE jsonb_exists_any(config->'supported_formats', ARRAY['lmstudio', 'ollama']);
