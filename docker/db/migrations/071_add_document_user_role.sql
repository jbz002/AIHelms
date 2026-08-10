-- 071_add_document_user_role.sql
-- 注册文档中心所需权限码（document:read/batch_extract、document_library:read/create；document:extract 已在 init.sql），
-- 种子 document_user 角色(is_system=false)并绑定 5 个权限码。
-- 普通用户持 document_user 角色后，可在 web 端文档中心浏览/测试接口、上传文档、AI 提取接口。
-- 这些权限码此前仅被代码引用、从未落库，管理员靠 is_admin 旁路访问；本迁移正式注册。

INSERT INTO aihelms.permissions (code, name, resource, action, description) VALUES
    ('document:read', '查看文档', 'document', 'read', '查看文档/库/接口列表与详情、调试代理'),
    ('document:batch_extract', '批量提取库接口', 'document', 'batch_extract', '批量提取库内文档接口'),
    ('document_library:read', '查看文档库', 'document_library', 'read', '查看文档库列表与详情'),
    ('document_library:create', '创建文档库', 'document_library', 'create', '创建文档库')
ON CONFLICT (code) DO NOTHING;

-- is_system=false：管理员可在 UI 调整该角色权限。
INSERT INTO aihelms.roles (name, display_name, description, is_system) VALUES
    ('document_user', 'API文档使用者', '可在 web 端文档中心浏览/测试接口、上传文档、AI 提取接口', false)
ON CONFLICT (name) DO NOTHING;

-- 绑定权限（按 name + code）。document:extract 已存在于 init.sql。
INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM aihelms.roles r, aihelms.permissions p
WHERE r.name = 'document_user'
  AND p.code IN ('document:read', 'document:extract', 'document:batch_extract',
                 'document_library:read', 'document_library:create')
ON CONFLICT (role_id, permission_id) DO NOTHING;
