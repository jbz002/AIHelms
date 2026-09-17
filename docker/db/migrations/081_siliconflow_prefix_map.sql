-- 081: 新增 SiliconFlow 供应商 LiteLLM 前缀映射
-- 背景：SiliconFlow（api.siliconflow.cn）为 OpenAI 兼容端点，但 LiteLLM v1.93
--   既无 siliconflow provider（LlmProviders 无此值），/rerank 也不支持 openai 前缀
--   （v1.93 rerank 支持集仅 cohere/azure_ai/jina_ai/together_ai/voyage/infinity/
--    hosted_vllm/nvidia_nim/deepinfra/fireworks_ai/bedrock/watsonx）。故：
--   - chat/embedding 走 openai 前缀，litellm 请求 {api_base}/chat/completions、/embeddings
--   - rerank 走 hosted_vllm 前缀，其 transform 把 api_base 规范为 {api_base}/rerank，
--     api_base 已含 /v1 时得到 .../v1/rerank，正是 SiliconFlow rerank 端点
-- api_base 形如 https://api.siliconflow.cn/v1 已含 /v1，needs_v1 保持 false。
INSERT INTO aihelms.provider_prefix_map (provider_type, format, category, prefix, needs_v1) VALUES
    ('siliconflow', 'openai', 'chat', 'openai', false),
    ('siliconflow', 'openai', 'embedding', 'openai', false),
    ('siliconflow', 'openai', 'rerank', 'hosted_vllm', false)
ON CONFLICT (provider_type, format, category) DO NOTHING;
