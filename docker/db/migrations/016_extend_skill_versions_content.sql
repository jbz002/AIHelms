-- 016_extend_skill_versions_content.sql
-- Module 04: Skill 渐进式披露 + 内容完整性
-- 在 skill_versions 上扩展内容解析/哈希/漂移字段，在 skills 上增加 frontmatter 快照

-- skill_versions: 来源类型 + URL 源地址
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(16) NOT NULL DEFAULT 'zip';
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS source_url TEXT DEFAULT '';

-- skill_versions: SKILL.md 解析结果
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS frontmatter JSONB DEFAULT '{}';
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS summary_text TEXT DEFAULT '';
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS full_content TEXT DEFAULT '';

-- skill_versions: 内容完整性（SHA-256 哈希 + 漂移检测）
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS composite_hash VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS file_hashes JSONB DEFAULT '{}';
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS drift_detected BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS drifted_files JSONB DEFAULT '[]';
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS last_drift_check_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_skill_versions_source_type ON aihelms.skill_versions(source_type);
CREATE INDEX IF NOT EXISTS idx_skill_versions_composite_hash ON aihelms.skill_versions(composite_hash);

-- skills: frontmatter + summary 快照（Card 视图直接查询，避免 JOIN 版本表）
ALTER TABLE aihelms.skills
    ADD COLUMN IF NOT EXISTS frontmatter JSONB DEFAULT '{}';
ALTER TABLE aihelms.skills
    ADD COLUMN IF NOT EXISTS summary_text TEXT DEFAULT '';
