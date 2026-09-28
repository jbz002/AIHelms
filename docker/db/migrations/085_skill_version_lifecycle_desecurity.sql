-- 085_skill_version_lifecycle_desecurity.sql
-- 安全审查退出 Skill 审批环节：版本生命周期收敛为 draft/published/yanked/deprecated。
-- 历史审查管线状态（scanning/pending_review/rejected）归一为 draft，可正常激活；
-- 安全审查结果字段保留，仅供审计中心手动执行展示。
UPDATE aihelms.skill_versions
SET lifecycle_status = 'draft'
WHERE lifecycle_status IN ('scanning', 'pending_review', 'rejected');
