-- 077: provider_prefix_map 补 ollama 双方言行
-- 背景：ollama.com 官方 coding plan 同时提供 anthropic(/v1/messages) 与 openai 两种协议端点，
-- 但覆盖表只有 format='ollama' 的历史行（词汇与凭证 format 的 anthropic/openai 不一致，永远查不中），
-- 导致 anthropic 方言凭证经 registry 派生拿到 'ollama' 前缀，litellm 走 openai 翻译路径丢 tool_use
-- （2026-08-26 生产事故，详见 dev/roadmap/模型接入去Anthropic后缀整改.md §八）。
-- 修复：补 (ollama, anthropic, chat)→anthropic 与 (ollama, openai, chat)→ollama；历史 'ollama' 行保留兼容。
INSERT INTO aihelms.provider_prefix_map (provider_type, format, category, prefix, needs_v1) VALUES
    ('ollama', 'anthropic', 'chat', 'anthropic', false),
    ('ollama', 'openai', 'chat', 'ollama', false)
ON CONFLICT (provider_type, format, category) DO NOTHING;
