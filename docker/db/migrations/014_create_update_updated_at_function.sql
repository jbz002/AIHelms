-- ====================================
-- 创建自动更新 updated_at 的触发器函数
-- ====================================

-- 在 aihelms schema 中创建 update_updated_at_column 函数
CREATE OR REPLACE FUNCTION aihelms.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 注：此函数供各表的触发器使用，自动在更新记录时设置 updated_at 为当前时间
