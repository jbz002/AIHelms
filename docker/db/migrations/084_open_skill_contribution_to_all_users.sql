-- 084_open_skill_contribution_to_all_users.sql
-- Skill 贡献全员开放：user 角色绑定 skill:contribute，所有普通用户可在 web 端贡献 Skill 草稿。
-- contributor 角色保留，仅继续承载 MCP/Agent 贡献权限，描述同步更新（不删行，符合 additive-only 规则）。
INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM aihelms.roles r, aihelms.permissions p
WHERE r.name = 'user' AND p.code = 'skill:contribute'
ON CONFLICT (role_id, permission_id) DO NOTHING;

UPDATE aihelms.roles
SET display_name = 'MCP/Agent 贡献者',
    description = '可在 web 端贡献 MCP Server 与智能体草稿（Skill 贡献已全员开放）'
WHERE name = 'contributor';
