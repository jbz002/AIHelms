-- 066: llm_call_logs + cost_summary_daily 增加 reasoning_tokens
-- 推理模型（DeepSeek-R1 / Qwen-QwQ / OpenAI o1 等）的 reasoning token 是 completion_tokens
-- 的子集（completion_tokens = reasoning + 非 reasoning 输出），provider 对 reasoning token
-- 单独计价（registry 键 output_cost_per_reasoning_token，52 模型有）。
-- 落表后成本计算按 output 拆分：
--   output_cost = output_cost_per_token * (completion - reasoning)
--               + output_cost_per_reasoning_token * reasoning
-- 仍属 token 维度，复用现有成本管道（与 cache_read/creation 同构），
-- 与多模态 per-image / per-second（Q20 非维度）语义不同。
ALTER TABLE aihelms.llm_call_logs ADD COLUMN IF NOT EXISTS reasoning_tokens INT DEFAULT 0;
ALTER TABLE aihelms.cost_summary_daily ADD COLUMN IF NOT EXISTS reasoning_tokens BIGINT DEFAULT 0;
