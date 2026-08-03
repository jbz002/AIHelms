-- 064: models 表增加 deprecation_date（注册表回填的模型弃用日期，前端据此警示）
ALTER TABLE aihelms.models ADD COLUMN IF NOT EXISTS deprecation_date DATE;
