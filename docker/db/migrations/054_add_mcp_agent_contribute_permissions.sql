-- 054_add_mcp_agent_contribute_permissions.sql
-- 注册 mcp:contribute / agent:contribute 权限码，并绑定到 053 种子的 contributor 角色。
-- 普通用户持 contributor 角色后，可在 web 端贡献自己的 MCP Server / 智能体草稿。
INSERT INTO aihelms.permissions (code, name, resource, action, description) VALUES
    ('mcp:contribute', '贡献 MCP', 'mcp', 'contribute', '普通用户在 web 端创建/编辑/提版本/提交发布审核自己的 MCP Server 草稿'),
    ('agent:contribute', '贡献智能体', 'agent', 'contribute', '普通用户在 web 端创建/编辑/提交发布审核自己的智能体草稿')
ON CONFLICT (code) DO NOTHING;

-- 绑定到 contributor 角色（按 name 命中 053 种子行或运行时同名角色）。
INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM aihelms.roles r, aihelms.permissions p
WHERE r.name = 'contributor' AND p.code IN ('mcp:contribute', 'agent:contribute')
ON CONFLICT (role_id, permission_id) DO NOTHING;
