-- 068_category_names_zh.sql
-- 把 Skill/MCP/Agent 英文分类名归一化为中文。
-- category 是自由文本列(非 FK),分类表 name 与实体表 category 各自独立存储,故双更新。
-- 纯数据修正,无 schema 变更;UPDATE 天然幂等,重复执行结果不变。
-- name 列有 UNIQUE 约束,执行前已确认目标中文名未先存在、无多对一冲突。

-- general → 通用
UPDATE aihelms.skill_categories  SET name = '通用'     WHERE name = 'general';
UPDATE aihelms.skills            SET category = '通用' WHERE category = 'general';
UPDATE aihelms.mcp_categories    SET name = '通用'     WHERE name = 'general';
UPDATE aihelms.mcp_servers       SET category = '通用' WHERE category = 'general';
UPDATE aihelms.agent_categories  SET name = '通用'     WHERE name = 'general';
UPDATE aihelms.agents            SET category = '通用' WHERE category = 'general';

-- dev → 开发
UPDATE aihelms.skill_categories  SET name = '开发'     WHERE name = 'dev';
UPDATE aihelms.skills            SET category = '开发' WHERE category = 'dev';
UPDATE aihelms.mcp_categories    SET name = '开发'     WHERE name = 'dev';
UPDATE aihelms.mcp_servers       SET category = '开发' WHERE category = 'dev';
UPDATE aihelms.agent_categories  SET name = '开发'     WHERE name = 'dev';
UPDATE aihelms.agents            SET category = '开发' WHERE category = 'dev';

-- legal → 法律
UPDATE aihelms.skill_categories  SET name = '法律'     WHERE name = 'legal';
UPDATE aihelms.skills            SET category = '法律' WHERE category = 'legal';
UPDATE aihelms.mcp_categories    SET name = '法律'     WHERE name = 'legal';
UPDATE aihelms.mcp_servers       SET category = '法律' WHERE category = 'legal';
UPDATE aihelms.agent_categories  SET name = '法律'     WHERE name = 'legal';
UPDATE aihelms.agents            SET category = '法律' WHERE category = 'legal';

-- office → 办公
UPDATE aihelms.skill_categories  SET name = '办公'     WHERE name = 'office';
UPDATE aihelms.skills            SET category = '办公' WHERE category = 'office';
UPDATE aihelms.mcp_categories    SET name = '办公'     WHERE name = 'office';
UPDATE aihelms.mcp_servers       SET category = '办公' WHERE category = 'office';
UPDATE aihelms.agent_categories  SET name = '办公'     WHERE name = 'office';
UPDATE aihelms.agents            SET category = '办公' WHERE category = 'office';

-- search → 搜索
UPDATE aihelms.skill_categories  SET name = '搜索'     WHERE name = 'search';
UPDATE aihelms.skills            SET category = '搜索' WHERE category = 'search';
UPDATE aihelms.mcp_categories    SET name = '搜索'     WHERE name = 'search';
UPDATE aihelms.mcp_servers       SET category = '搜索' WHERE category = 'search';
UPDATE aihelms.agent_categories  SET name = '搜索'     WHERE name = 'search';
UPDATE aihelms.agents            SET category = '搜索' WHERE category = 'search';

-- general search → 通用搜索(用户点名,本地无但 prod 可能存在)
UPDATE aihelms.skill_categories  SET name = '通用搜索'     WHERE name = 'general search';
UPDATE aihelms.skills            SET category = '通用搜索' WHERE category = 'general search';
UPDATE aihelms.mcp_categories    SET name = '通用搜索'     WHERE name = 'general search';
UPDATE aihelms.mcp_servers       SET category = '通用搜索' WHERE category = 'general search';
UPDATE aihelms.agent_categories  SET name = '通用搜索'     WHERE name = 'general search';
UPDATE aihelms.agents            SET category = '通用搜索' WHERE category = 'general search';
