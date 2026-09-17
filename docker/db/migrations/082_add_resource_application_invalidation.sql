-- 资源申请失效标记：模型取消发布等场景，已批准授权随资源下线失效
ALTER TABLE aihelms.resource_applications
    ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS invalidation_reason TEXT DEFAULT '';
