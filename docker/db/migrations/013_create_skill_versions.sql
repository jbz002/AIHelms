-- Skill 版本管理：每个 Skill 的多版本内容快照 + 版本元信息 + 版本绑定安全审查
-- 设计：主表 skills 存「跨版本稳定元数据 + 当前 active 版本指针 + active 版本内容/安全冗余快照」；
--       子表 skill_versions 存每个版本的 zip 路径、提示词与生命周期状态。
-- Skill 不进 LiteLLM，激活无外部同步；版本内容变更需先通过版本绑定安全审查（硬门控）才能激活。

-- 1. 版本子表（skills 已存在，skill_id 外键可直接声明）
CREATE TABLE IF NOT EXISTS aihelms.skill_versions (
    id BIGSERIAL PRIMARY KEY,
    skill_id BIGINT NOT NULL REFERENCES aihelms.skills(id) ON DELETE CASCADE,
    version VARCHAR(64) NOT NULL,
    version_label VARCHAR(128) NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT false,
    lifecycle_status VARCHAR(20) NOT NULL DEFAULT 'inactive',
    sunset_date TIMESTAMPTZ,
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
    content_sha256 VARCHAR(64) NOT NULL DEFAULT '',
    zip_path VARCHAR(500) NOT NULL DEFAULT '',
    zip_size BIGINT NOT NULL DEFAULT 0,
    zip_filename VARCHAR(200) NOT NULL DEFAULT '',
    agent_install_prompt TEXT NOT NULL DEFAULT '',
    usage_instructions TEXT NOT NULL DEFAULT '',
    change_log TEXT NOT NULL DEFAULT '',
    security_status VARCHAR(32) NOT NULL DEFAULT 'not_scanned',
    security_decision VARCHAR(32) NOT NULL DEFAULT '',
    security_severity VARCHAR(32) NOT NULL DEFAULT '',
    security_risk_score INTEGER NOT NULL DEFAULT 0,
    latest_ai_policies_audit_id BIGINT REFERENCES aihelms.ai_policies_audits(id) ON DELETE SET NULL,
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(skill_id, version)
);

CREATE INDEX IF NOT EXISTS idx_skill_versions_skill ON aihelms.skill_versions(skill_id);
-- 每个逻辑 Skill 至多 1 个 active（部分唯一索引，DB 层保证单 active 不变式）
CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_versions_active
    ON aihelms.skill_versions(skill_id) WHERE is_active = true;

-- 2. 主表加 active 版本指针（skill_versions 已存在，FK 可内联）
ALTER TABLE aihelms.skills
    ADD COLUMN IF NOT EXISTS current_version_id BIGINT
    REFERENCES aihelms.skill_versions(id) ON DELETE SET NULL;

-- 3. 审查表加版本绑定指针（skill_versions 已存在），用于版本绑定安全审查
ALTER TABLE aihelms.ai_policies_audits
    ADD COLUMN IF NOT EXISTS skill_version_id BIGINT
    REFERENCES aihelms.skill_versions(id) ON DELETE SET NULL;

-- 4. 存量回填：为每条 skills 建一条 v1 active 版本（内容/安全字段从主表拷贝，v1 复用既有 zip 文件，不拷贝）
INSERT INTO aihelms.skill_versions (
    skill_id, version, version_label, is_active, lifecycle_status, source,
    content_sha256, zip_path, zip_size, zip_filename, agent_install_prompt,
    usage_instructions, change_log, security_status, security_decision,
    security_severity, security_risk_score, latest_ai_policies_audit_id, created_by
)
SELECT
    s.id, '1.0.0', '', true, 'active', 'manual',
    '', s.zip_path, s.zip_size, s.zip_filename, s.agent_install_prompt,
    s.usage_instructions, 'backfill from existing record',
    s.security_status, s.security_decision, s.security_severity,
    s.security_risk_score, s.latest_ai_policies_audit_id, s.created_by
FROM aihelms.skills s
WHERE NOT EXISTS (
    SELECT 1 FROM aihelms.skill_versions v WHERE v.skill_id = s.id
);

-- 5. 回填 current_version_id 指针指向各自的 active 版本
UPDATE aihelms.skills s
SET current_version_id = (
    SELECT v.id FROM aihelms.skill_versions v
    WHERE v.skill_id = s.id AND v.is_active = true
    LIMIT 1
)
WHERE s.current_version_id IS NULL;
