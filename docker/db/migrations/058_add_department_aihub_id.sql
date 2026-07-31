-- 058: departments 表加 AIHub 部门外部 id 列
-- 用于 SSO 登录时按 aihub_department_id upsert 匹配本地部门
-- 普通 unique index：postgres unique 允许多个 NULL，本地手动部门(无 aihub_id)不冲突
ALTER TABLE aihelms.departments ADD COLUMN IF NOT EXISTS aihub_department_id VARCHAR(100);

CREATE UNIQUE INDEX IF NOT EXISTS idx_departments_aihub_id
    ON aihelms.departments (aihub_department_id);
