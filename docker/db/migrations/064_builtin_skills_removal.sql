-- 064 · 移除内置 Skills（S8）功能
-- 功能下线：删除 skills 表 is_builtin / builtin_slug 列与索引（幂等）。
-- 历史：034_builtin_skills.sql 新增；init.sql 已同步移除列定义，本迁移清理已部署库的残留列。
-- 注意：项目默认 migration additive-only；本次为功能下线的逆向清理，经明确授权。

ALTER TABLE aihelms.skills DROP COLUMN IF EXISTS is_builtin;
ALTER TABLE aihelms.skills DROP COLUMN IF EXISTS builtin_slug;
DROP INDEX IF EXISTS aihelms.idx_skills_builtin_slug;
