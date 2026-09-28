-- 087_mcp_agent_department_visibility.sql
-- MCP / 智能体补部门可见（对齐 Skill 086 的形态），可见性收敛为 all/department 两选：
-- 1. mcp_servers 加 visible_department_id（visibility_type='department' 时生效）
-- 2. agents 加 visibility_type（默认 all）+ visible_department_id
-- 3. 存量 private/unlisted/selected 归一为 all（prod 实查三类存量均为 0，防御直写库脏值）

ALTER TABLE aihelms.mcp_servers
    ADD COLUMN IF NOT EXISTS visible_department_id BIGINT REFERENCES aihelms.departments(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_servers_visible_department ON aihelms.mcp_servers(visible_department_id);

ALTER TABLE aihelms.agents
    ADD COLUMN IF NOT EXISTS visibility_type VARCHAR(20) NOT NULL DEFAULT 'all';

ALTER TABLE aihelms.agents
    ADD COLUMN IF NOT EXISTS visible_department_id BIGINT REFERENCES aihelms.departments(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_agents_visible_department ON aihelms.agents(visible_department_id);

UPDATE aihelms.mcp_servers
SET visibility_type = 'all'
WHERE visibility_type NOT IN ('all', 'department');

UPDATE aihelms.agents
SET visibility_type = 'all'
WHERE visibility_type NOT IN ('all', 'department');
