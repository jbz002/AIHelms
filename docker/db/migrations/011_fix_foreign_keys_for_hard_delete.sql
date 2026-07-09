-- ====================================
-- Soft Delete → Hard Delete 外键约束修复
-- 将 user 相关的 RESTRICT 外键改为 SET NULL，支持用户硬删除时保留历史数据
-- ====================================

-- 1. usage_logs.user_id — 历史调用日志，用户删除后保留日志但置 NULL
ALTER TABLE aihelms.usage_logs
    DROP CONSTRAINT IF EXISTS usage_logs_user_id_fkey,
    ADD CONSTRAINT usage_logs_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES aihelms.users(id) ON DELETE SET NULL;

-- 2. resource_applications.user_id — 资源申请记录，用户删除后保留记录但置 NULL
ALTER TABLE aihelms.resource_applications
    DROP CONSTRAINT IF EXISTS resource_applications_user_id_fkey,
    ADD CONSTRAINT resource_applications_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES aihelms.users(id) ON DELETE SET NULL;

-- 3. resource_applications.reviewed_by — 审批人删除后保留记录但置 NULL
ALTER TABLE aihelms.resource_applications
    DROP CONSTRAINT IF EXISTS resource_applications_reviewed_by_fkey,
    ADD CONSTRAINT resource_applications_reviewed_by_fkey
        FOREIGN KEY (reviewed_by) REFERENCES aihelms.users(id) ON DELETE SET NULL;

-- 4. agent_usage_logs.user_id — 智能体使用日志，用户删除后保留日志但置 NULL
ALTER TABLE aihelms.agent_usage_logs
    DROP CONSTRAINT IF EXISTS agent_usage_logs_user_id_fkey,
    ADD CONSTRAINT agent_usage_logs_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES aihelms.users(id) ON DELETE SET NULL;
