-- S4 · Skill Tag + Label 双层体系
--   skill_tags       版本别名（beta/stable/latest），latest 为系统保留只读指针
--   label_definitions 治理 Label 定义（recommended/official/verified，display_name_key 走前端 i18n）
--   skill_labels     Skill-Label 关联（运营标签授予）
-- idempotent / additive-only。

-- ─── 版本别名 Tag ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aihelms.skill_tags (
    id BIGSERIAL PRIMARY KEY,
    skill_id BIGINT NOT NULL REFERENCES aihelms.skills(id) ON DELETE CASCADE,
    tag_name VARCHAR(32) NOT NULL,
    version_id BIGINT NOT NULL REFERENCES aihelms.skill_versions(id) ON DELETE CASCADE,
    is_system BOOLEAN NOT NULL DEFAULT false,   -- latest 等系统保留 tag
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_skill_tags_skill_tag UNIQUE (skill_id, tag_name)
);

CREATE INDEX IF NOT EXISTS idx_skill_tags_skill ON aihelms.skill_tags(skill_id);
CREATE INDEX IF NOT EXISTS idx_skill_tags_version ON aihelms.skill_tags(version_id);

-- ─── 治理 Label 定义 ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aihelms.label_definitions (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(32) NOT NULL UNIQUE,
    display_name_key VARCHAR(64) NOT NULL,      -- i18n key（不存翻译文本）
    color VARCHAR(16) NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Skill-Label 关联 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aihelms.skill_labels (
    id BIGSERIAL PRIMARY KEY,
    skill_id BIGINT NOT NULL REFERENCES aihelms.skills(id) ON DELETE CASCADE,
    label_id BIGINT NOT NULL REFERENCES aihelms.label_definitions(id),
    granted_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note TEXT NOT NULL DEFAULT '',
    CONSTRAINT uq_skill_labels_skill_label UNIQUE (skill_id, label_id)
);

CREATE INDEX IF NOT EXISTS idx_skill_labels_skill ON aihelms.skill_labels(skill_id);

-- 预置 Label（翻译文本走前端 i18n，DB 只存 key）
INSERT INTO aihelms.label_definitions (name, display_name_key, color, sort_order, is_active) VALUES
    ('recommended', 'label.recommended.title', 'green', 10, true),
    ('official', 'label.official.title', 'blue', 20, true),
    ('verified', 'label.verified.title', 'purple', 30, true)
ON CONFLICT (name) DO NOTHING;

-- 治理 Label 管理权限点（仅注册，不写 role_permissions；管理员由 is_admin 统一放行）
INSERT INTO aihelms.permissions (code, name, resource, action, description) VALUES
    ('skill:label:manage', '管理Skill治理标签', 'skill', 'label_manage', '授予/撤销 Skill 治理标签、维护标签定义')
ON CONFLICT (code) DO NOTHING;

