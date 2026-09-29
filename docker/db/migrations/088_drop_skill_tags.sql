-- 移除 Skill 版本别名 Tag 功能（skill_tags 表整体删除）。
-- 版本别名/Tag 无实际使用价值，前后端代码与 API 已同步移除。

DROP TABLE IF EXISTS aihelms.skill_tags;
