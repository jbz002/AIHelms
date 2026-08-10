-- 072_add_document_ownership_perms.sql
-- 注册文档/文档库 update/delete 权限码（此前仅被代码引用、从未落库，管理员靠 is_admin 旁路）。
-- 将 web 文档中心所需的 3 个写权限绑给 document_user（document:update 不绑：web 不做正文编辑，admin 独占）。
-- 配合后端 ownership 校验：document_user 只能增删改自己创建的库/文档，他人资源只读预览。

INSERT INTO aihelms.permissions (code, name, resource, action, description) VALUES
    ('document:update', '更新文档', 'document', 'update', '更新文档内容'),
    ('document:delete', '删除文档', 'document', 'delete', '删除文档'),
    ('document_library:update', '更新文档库', 'document_library', 'update', '重命名/修改描述'),
    ('document_library:delete', '删除文档库', 'document_library', 'delete', '删除知识库及关联数据')
ON CONFLICT (code) DO NOTHING;

INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM aihelms.roles r, aihelms.permissions p
WHERE r.name = 'document_user'
  AND p.code IN ('document:delete', 'document_library:update', 'document_library:delete')
ON CONFLICT (role_id, permission_id) DO NOTHING;
