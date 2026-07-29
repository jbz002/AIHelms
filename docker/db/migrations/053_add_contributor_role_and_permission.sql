-- 053_add_contributor_role_and_permission.sql
-- 注册 skill:contribute 权限码，种子 contributor 角色(is_system=false)并绑定权限。
-- 普通用户持 contributor 角色 + skill:contribute 后，可在 web 端贡献自己的 Skill 草稿。
INSERT INTO aihelms.permissions (code, name, resource, action, description) VALUES
    ('skill:contribute', '贡献 Skill', 'skill', 'contribute', '普通用户在 web 端创建/编辑/提版本/提交发布审核自己的 Skill 草稿')
ON CONFLICT (code) DO NOTHING;

-- is_system=false：管理员可在 UI 调整该角色权限。
-- ON CONFLICT (name) DO NOTHING：若运行时已存在用户自建的 'contributor' 同名角色，不覆盖其属性。
INSERT INTO aihelms.roles (name, display_name, description, is_system) VALUES
    ('contributor', 'Skill 贡献者', '可在 web 端贡献 Skill 草稿并提发布审核', false)
ON CONFLICT (name) DO NOTHING;

-- 绑定权限（按 name）。若已存在用户自建同名 contributor 角色，此处绑定到该行。
INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM aihelms.roles r, aihelms.permissions p
WHERE r.name = 'contributor' AND p.code = 'skill:contribute'
ON CONFLICT (role_id, permission_id) DO NOTHING;
