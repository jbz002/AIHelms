-- 026: 可见性增强（private/unlisted）+ 发布前门控（模块 07 可见性增强与发布门控）
-- skills 补 visibility_type 列（Model/McpServer/CustomEntity 已有，Skill 此前缺失）
-- publish_reviews：发布评审单（创建者申请发布 → 管理员审核 → is_published=true）
-- publish_settings：发布门控全局开关单例表（仿 ai_policies_settings，默认关）

-- (1) Skill 补 visibility_type 列
ALTER TABLE aihelms.skills
    ADD COLUMN IF NOT EXISTS visibility_type VARCHAR(20) NOT NULL DEFAULT 'all';
CREATE INDEX IF NOT EXISTS idx_skills_visibility ON aihelms.skills(visibility_type);

-- (2) 发布评审单
CREATE TABLE IF NOT EXISTS aihelms.publish_reviews (
    id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(32) NOT NULL,        -- mcp_server / skill / custom_entity
    entity_id BIGINT NOT NULL,
    requested_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending / approved / rejected / withdrawn
    review_notes TEXT NOT NULL DEFAULT '',
    reviewed_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_publish_reviews_entity
    ON aihelms.publish_reviews(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_publish_reviews_status
    ON aihelms.publish_reviews(status);
CREATE INDEX IF NOT EXISTS idx_publish_reviews_requested_by
    ON aihelms.publish_reviews(requested_by);

CREATE TRIGGER trg_publish_reviews_updated_at
    BEFORE UPDATE ON aihelms.publish_reviews
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();

-- (3) 发布门控全局开关单例表
CREATE TABLE IF NOT EXISTS aihelms.publish_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    publish_review_enabled BOOLEAN NOT NULL DEFAULT false,
    updated_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT publish_settings_singleton CHECK (id = 1)
);

INSERT INTO aihelms.publish_settings (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;
