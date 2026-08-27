-- 078: ollama openai 方言前缀 ollama -> openai（077 所插行的修正）
-- 背景：litellm 的 'ollama/' 前缀走 ollama 原生协议 handler（打 /api/chat），
--   1.93 对 ollama.com 原生响应中的 tool_call 翻译缺失，工具调用以裸文本流出
--   （2026-08-27 生产事故：opencode 客户端走裸名组调工具卡死，详见
--    dev/roadmap/模型接入去Anthropic后缀整改.md §九）。
-- ollama.com 官方提供标准 openai 兼容端点 /v1/chat/completions（直连实测
--   tool_calls 完整），故 openai 方言改用 openai handler + api_base 补 /v1。
-- 077 已在 dev/prod 应用过且规则不允许修改既有迁移，用本迁移 UPDATE 修正。
UPDATE aihelms.provider_prefix_map
SET prefix = 'openai', needs_v1 = true
WHERE provider_type = 'ollama' AND format = 'openai' AND category = 'chat';
