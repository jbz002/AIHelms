-- 049_add_platform_settings_permissions.sql
-- 注册 platform_settings 权限码并关联到 super_admin/admin 角色（仿 037 publish_review）。
INSERT INTO aihelms.permissions (code, name, resource, action, description) VALUES
    ('platform_settings:read', '查看平台设置', 'platform_settings', 'read', '查看平台默认模型等平台级设置'),
    ('platform_settings:config', '配置平台设置', 'platform_settings', 'config', '更新平台默认模型等平台级设置')
ON CONFLICT (code) DO NOTHING;

INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM aihelms.roles r, aihelms.permissions p
WHERE r.name IN ('super_admin', 'admin')
  AND p.code IN ('platform_settings:read', 'platform_settings:config')
ON CONFLICT (role_id, permission_id) DO NOTHING;
