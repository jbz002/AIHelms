-- ====================================
-- 自定义实体类型与实例表
-- 支持管理员在运行时定义新的资产目录类型
-- ====================================

-- 类型定义表
CREATE TABLE IF NOT EXISTS aihelms.custom_entity_types (
    id BIGSERIAL PRIMARY KEY,
    type_key VARCHAR(64) NOT NULL UNIQUE,           -- 如 llm_prompt / model_card / n8n_workflow
    display_name VARCHAR(128) NOT NULL,
    description TEXT DEFAULT '',
    icon VARCHAR(20) DEFAULT '🧩',
    schema_definition JSONB NOT NULL DEFAULT '{}',   -- JSON Schema（字段定义、类型、必填、约束）
    searchable_fields JSONB DEFAULT '[]',           -- 哪些 data 字段纳入词法检索
    is_active BOOLEAN DEFAULT true,
    is_published BOOLEAN DEFAULT false,               -- 类型发布后用户端可见
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    -- 约束
    CONSTRAINT chk_type_key_format CHECK (type_key ~ '^[a-z0-9_-]+$')
);

-- 实体实例表
CREATE TABLE IF NOT EXISTS aihelms.custom_entities (
    id BIGSERIAL PRIMARY KEY,
    type_id BIGINT NOT NULL REFERENCES aihelms.custom_entity_types(id) ON DELETE CASCADE,
    type_key VARCHAR(64) NOT NULL,                    -- 冗余（便于跨实体检索/过滤）
    name VARCHAR(200) NOT NULL,                      -- 独立列：高频查询/展示
    data JSONB NOT NULL DEFAULT '{}',                 -- 实例数据，按 schema_definition 校验
    content_text TEXT DEFAULT '',                     -- 冗余：用于 embedding 的拼接文本
    description TEXT DEFAULT '',                      -- 独立列：列表/搜索展示
    tags JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT true,
    is_published BOOLEAN DEFAULT false,
    visibility_type VARCHAR(20) DEFAULT 'all',        -- 复用现有可见性模型
    requires_approval BOOLEAN DEFAULT false,
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 索引策略
CREATE INDEX IF NOT EXISTS idx_custom_entities_type ON aihelms.custom_entities(type_id);
CREATE INDEX IF NOT EXISTS idx_custom_entities_type_key ON aihelms.custom_entities(type_key);
CREATE INDEX IF NOT EXISTS idx_custom_entities_published ON aihelms.custom_entities(is_published);
CREATE INDEX IF NOT EXISTS idx_custom_entities_visibility ON aihelms.custom_entities(visibility_type);
CREATE INDEX IF NOT EXISTS idx_custom_entities_data ON aihelms.custom_entities USING gin (data);
CREATE INDEX IF NOT EXISTS idx_custom_entities_name ON aihelms.custom_entities(name);
CREATE INDEX IF NOT EXISTS idx_custom_entities_created_by ON aihelms.custom_entities(created_by);

-- 触发器：自动更新 updated_at
CREATE TRIGGER update_custom_entity_types_updated_at
    BEFORE UPDATE ON aihelms.custom_entity_types
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();

CREATE TRIGGER update_custom_entities_updated_at
    BEFORE UPDATE ON aihelms.custom_entities
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();
