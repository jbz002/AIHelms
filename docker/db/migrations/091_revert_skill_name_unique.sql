-- 091: 撤回 090 单名称契约——name 恢复普通索引（表单自由填、可与 frontmatter 不同），
-- 并恢复 090 收敛掉的存量中文名。幂等：未跑过 090 的库全部 no-op。

DROP INDEX IF EXISTS aihelms.uq_skills_name;
CREATE INDEX IF NOT EXISTS idx_skills_name ON aihelms.skills(name);

-- 090 曾按 frontmatter 覆盖的 3 个存量名（preflight 2026-10-07 实录），恢复原名。
-- 唯一索引下 name 匹配至多一行；090 后若有人改过名则 miss no-op。
UPDATE aihelms.skills SET name = '爬取任务表单生成' WHERE name = 'docs-crawl-scout';
UPDATE aihelms.skills SET name = 'AIHelms 技能维护' WHERE name = 'skill-maintenance';
UPDATE aihelms.skills SET name = 'AIHelms AI身份对接' WHERE name = 'aihub-integration';
