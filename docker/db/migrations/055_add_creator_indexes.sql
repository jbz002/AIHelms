-- 055_add_creator_indexes.sql
-- 为 mcp_servers / agents 补 created_by 索引。
-- contributor 工作台按创建者列表/计数（find_all_*_by_creator / count_*_by_creator）
-- 原先无索引走全表扫，随资源总量劣化；created_by 为过滤列，加索引定值。
CREATE INDEX IF NOT EXISTS idx_mcp_servers_created_by
    ON aihelms.mcp_servers(created_by);
CREATE INDEX IF NOT EXISTS idx_agents_created_by
    ON aihelms.agents(created_by);
