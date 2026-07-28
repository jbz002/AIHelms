-- 048_create_platform_settings.sql
-- 平台级设置单例表：default_model_id 为平台 LLM 调用（文档搜索 AI 总结等）的默认模型。
-- id 固定为 1（singleton），不存在时由应用层自动初始化。
CREATE TABLE IF NOT EXISTS aihelms.platform_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    default_model_id BIGINT REFERENCES aihelms.models(id) ON DELETE SET NULL,
    updated_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT platform_settings_singleton CHECK (id = 1)
);

INSERT INTO aihelms.platform_settings (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;
