-- 017_registration_hardening.sql
-- Module 05: 注册流程强化（SSRF 校验 + 重复检查 + 安全流水线通用化）

-- 1. ai_policies_audits 通用化：支持 MCP 等实体类型
ALTER TABLE aihelms.ai_policies_audits
    ADD COLUMN IF NOT EXISTS entity_type VARCHAR(16) NOT NULL DEFAULT 'skill';
ALTER TABLE aihelms.ai_policies_audits
    ADD COLUMN IF NOT EXISTS entity_id BIGINT;
ALTER TABLE aihelms.ai_policies_audits
    ADD COLUMN IF NOT EXISTS entity_name VARCHAR(128) NOT NULL DEFAULT '';
ALTER TABLE aihelms.ai_policies_audits
    ADD COLUMN IF NOT EXISTS entity_version VARCHAR(64) NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_ai_policies_audits_entity
    ON aihelms.ai_policies_audits(entity_type, entity_id);

-- 2. MCP 重复检查索引：url + transport 组合
CREATE INDEX IF NOT EXISTS idx_mcp_servers_url_transport
    ON aihelms.mcp_servers(url, transport);

-- 3. Skill 名称索引（重复检查用）
CREATE INDEX IF NOT EXISTS idx_skills_name ON aihelms.skills(name);

-- 4. MCP servers 安全状态字段
ALTER TABLE aihelms.mcp_servers
    ADD COLUMN IF NOT EXISTS security_status VARCHAR(32) NOT NULL DEFAULT 'not_scanned';
ALTER TABLE aihelms.mcp_servers
    ADD COLUMN IF NOT EXISTS security_decision VARCHAR(32) NOT NULL DEFAULT '';
ALTER TABLE aihelms.mcp_servers
    ADD COLUMN IF NOT EXISTS security_severity VARCHAR(32) NOT NULL DEFAULT '';
ALTER TABLE aihelms.mcp_servers
    ADD COLUMN IF NOT EXISTS security_risk_score INTEGER NOT NULL DEFAULT 0;
ALTER TABLE aihelms.mcp_servers
    ADD COLUMN IF NOT EXISTS latest_ai_policies_audit_id BIGINT
    REFERENCES aihelms.ai_policies_audits(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_servers_security_status
    ON aihelms.mcp_servers(security_status);
