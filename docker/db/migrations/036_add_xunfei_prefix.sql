-- 036_add_xunfei_prefix.sql
-- 讯飞星火 coding plan：提供两套兼容端点
--   OpenAI 格式    https://maas-coding-api.cn-huabei-1.xf-yun.com/v2
--   Anthropic 格式 https://maas-coding-api.cn-huabei-1.xf-yun.com/anthropic
-- api_base 已含完整路径（/v2 或 /anthropic），needs_v1=false 避免平台再补 /v1 导致路径错误。
INSERT INTO aihelms.provider_prefix_map (provider_type, format, category, prefix, needs_v1)
VALUES
  ('xunfei', 'openai',    'chat', 'openai',    false),
  ('xunfei', 'anthropic', 'chat', 'anthropic', false)
ON CONFLICT (provider_type, format, category) DO NOTHING;
