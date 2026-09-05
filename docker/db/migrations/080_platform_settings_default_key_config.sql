-- 080: 平台设置新增新用户默认 Key 预算/限流配置（仅作用于自动创建的个人主 Key）
ALTER TABLE aihelms.platform_settings
    ADD COLUMN IF NOT EXISTS default_key_budget_limit NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS default_key_budget_hard_limit BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS default_key_budget_duration VARCHAR(10),
    ADD COLUMN IF NOT EXISTS default_key_rate_limit_mode VARCHAR(10) NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS default_key_tpm_limit INTEGER,
    ADD COLUMN IF NOT EXISTS default_key_rpm_limit INTEGER,
    ADD COLUMN IF NOT EXISTS default_key_max_parallel_requests INTEGER;
