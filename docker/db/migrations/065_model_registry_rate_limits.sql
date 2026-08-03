-- 065: models 表增加 registry_rpm/registry_tpm
-- 注册表（LiteLLM model_prices_and_context_window.json 快照）声明的 provider 对该模型的
-- 速率硬限（RPM/TPM）。只读快照，供前端展示模型官方吞吐能力；
-- 与平台限流配置（ai_keys.rpm_limit / ai_key_model_limits.rpm）语义不同，不参与 LiteLLM 同步限流。
ALTER TABLE aihelms.models ADD COLUMN IF NOT EXISTS registry_rpm INT;
ALTER TABLE aihelms.models ADD COLUMN IF NOT EXISTS registry_tpm INT;
