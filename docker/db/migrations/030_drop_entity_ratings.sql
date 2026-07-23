-- 030: 移除评分反馈功能（公司内部场景不需要）
-- 删除模块 06 引入的 entity_ratings / entity_rating_stats 两表
-- DROP TABLE 自动级联删除其上的索引、约束、触发器，无需单独清理
-- 关联历史迁移：025 建表、029 加 lock_version；本迁移为功能移除终点

DROP TABLE IF EXISTS aihelms.entity_ratings;
DROP TABLE IF EXISTS aihelms.entity_rating_stats;
