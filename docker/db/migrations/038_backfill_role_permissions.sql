-- 038_backfill_role_permissions.sql
-- 回填 super_admin/admin 缺失的权限码关联。
-- 历史增量 migration 新增权限码（如 cli_token:*、skill:label:manage）时未同步回填
-- super_admin/admin 角色，导致这两类管理员在 is_admin=false 的纯权限校验路径下拿不到对应能力。
-- ai_policies:* 按设计仅靠 is_admin 放行（见 init.sql 注释），不写入 role_permissions，此处保持。
INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM aihelms.roles r, aihelms.permissions p
WHERE r.name = 'super_admin' AND p.resource <> 'ai_policies'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM aihelms.roles r, aihelms.permissions p
WHERE r.name = 'admin'
  AND p.resource <> 'ai_policies'
  AND p.code NOT IN ('role:create', 'role:update', 'role:delete')
ON CONFLICT (role_id, permission_id) DO NOTHING;
