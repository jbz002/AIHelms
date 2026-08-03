-- 062: crawl_tasks 加部分入库统计字段
-- pages_backfilled: SSE 断连期间从 docs-mcp crawl_results 回补的页数（真·中断信号）
-- pages_empty: 入库时内容为空未向量化的页数（真·内容缺失信号）
-- 用途：is_partial 徽章改基于真信号（backfilled>0 或 empty>0），
--       不再用 pages_total（scraper 发现数，含超深/失败未处理链接）误报。
ALTER TABLE aihelms.crawl_tasks
    ADD COLUMN IF NOT EXISTS pages_backfilled INT NOT NULL DEFAULT 0;
ALTER TABLE aihelms.crawl_tasks
    ADD COLUMN IF NOT EXISTS pages_empty INT NOT NULL DEFAULT 0;
