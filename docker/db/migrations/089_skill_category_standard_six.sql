-- Skill 分类标准化：标准六类中文枚举（通用/编程开发/办公效率/数据分析/文档处理/设计创作）
-- + 遗留数据收敛，为服务层硬校验（skill_service._validate_category）铺数据。
-- 仅动 skill 侧两张表；agent/mcp 分类体系独立，不在范围。幂等：已收敛库全部 no-op。
-- init.sql 已双写同形中文种子；068 曾把英文归一为中文短名，此处短名→标准全名。

-- 1) 短名→标准全名（registry + skills 双更新；NOT EXISTS 守卫 UNIQUE：
--    管理员若已手工建全名，跳过 registry 改名，skills 行仍归并）
UPDATE aihelms.skills SET category = '编程开发' WHERE category = '开发';
UPDATE aihelms.skill_categories SET name = '编程开发'
WHERE name = '开发'
  AND NOT EXISTS (SELECT 1 FROM aihelms.skill_categories c WHERE c.name = '编程开发');

UPDATE aihelms.skills SET category = '办公效率' WHERE category = '办公';
UPDATE aihelms.skill_categories SET name = '办公效率'
WHERE name = '办公'
  AND NOT EXISTS (SELECT 1 FROM aihelms.skill_categories c WHERE c.name = '办公效率');

-- 2) 兜底：068 之后经无校验链路新写入的 'general'（旧默认值/旧调用方）→ 通用
UPDATE aihelms.skills SET category = '通用' WHERE category = 'general';

-- 3) 补插缺失标准类
INSERT INTO aihelms.skill_categories (name, sort_order) VALUES
    ('数据分析', 30),
    ('文档处理', 40),
    ('设计创作', 50)
ON CONFLICT (name) DO NOTHING;

-- 4) 排序固定：标准六类 0-50 阶梯置前，存量 法律/搜索 顺延 60/70
UPDATE aihelms.skill_categories SET sort_order = 0  WHERE name = '通用';
UPDATE aihelms.skill_categories SET sort_order = 10 WHERE name = '编程开发';
UPDATE aihelms.skill_categories SET sort_order = 20 WHERE name = '办公效率';
UPDATE aihelms.skill_categories SET sort_order = 30 WHERE name = '数据分析';
UPDATE aihelms.skill_categories SET sort_order = 40 WHERE name = '文档处理';
UPDATE aihelms.skill_categories SET sort_order = 50 WHERE name = '设计创作';
UPDATE aihelms.skill_categories SET sort_order = 60 WHERE name = '法律';
UPDATE aihelms.skill_categories SET sort_order = 70 WHERE name = '搜索';
