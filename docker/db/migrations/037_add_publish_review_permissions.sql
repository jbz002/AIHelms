-- 037_add_publish_review_permissions.sql
-- 注册 publish_review 权限码并关联到 super_admin/admin 角色。
-- 此前 publish_review 仅用于表名/列名（publish_reviews 表、publish_review_enabled 列），
-- 未注册进 permissions 表，导致非管理员（is_admin=false）用户永远无法获得发布审核权限，
-- 「发布审核」菜单对他们也不可见。被 require_permission 的 is_admin 短路掩盖。
INSERT INTO aihelms.permissions (code, name, resource, action, description) VALUES
    ('publish_review:read', '查看发布审核', 'publish_review', 'read', '查看发布审核申请列表和详情'),
    ('publish_review:approve', '审核发布申请', 'publish_review', 'approve', '审核通过或驳回发布申请')
ON CONFLICT (code) DO NOTHING;

-- super_admin 全权限、admin 除角色管理外全权限，均应持有发布审核权限。
INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM aihelms.roles r, aihelms.permissions p
WHERE r.name IN ('super_admin', 'admin')
  AND p.code IN ('publish_review:read', 'publish_review:approve')
ON CONFLICT (role_id, permission_id) DO NOTHING;
