-- 086_skill_department_visibility.sql
-- Skill 部门可见性 + 简化贡献流程存量数据归一：
-- 1. skills 加 visible_department_id（visibility_type='department' 时生效，独立列非 JSONB）
-- 2. 存量已激活版本补 lifecycle 状态（安全审查退出审批后 draft→published 翻转缺口）
-- 3. 存量贡献者 Skill 领用免审批（原贡献链路硬编码 requires_approval=true）
-- 4. 第 3 条翻开的已发布 Skill 补广播进全体个人主 Key（否则用户端 MyIdentity 不可见）

ALTER TABLE aihelms.skills
    ADD COLUMN IF NOT EXISTS visible_department_id BIGINT REFERENCES aihelms.departments(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_skills_visible_department ON aihelms.skills(visible_department_id);

UPDATE aihelms.skill_versions
SET lifecycle_status = 'published'
WHERE is_active = true AND lifecycle_status = 'draft';

UPDATE aihelms.skills
SET requires_approval = false
WHERE requires_approval = true
  AND created_by IN (SELECT id FROM aihelms.users WHERE is_admin = false);

UPDATE aihelms.ai_keys k
SET skills = k.skills || to_jsonb(ARRAY[s.id])
FROM aihelms.skills s
WHERE s.is_published = true
  AND s.requires_approval = false
  AND s.hidden = false
  AND s.visibility_type IN ('all', 'selected')
  AND k.key_type = 'personal_main'
  AND k.is_active = true
  AND NOT k.skills @> to_jsonb(ARRAY[s.id]);
