-- 067: crawl_tasks 加 paused_from 列,记录任务从哪个相位(crawling|ingesting)暂停,
-- 供恢复时决定调 docs-mcp resume 还是重投 celery ingest。
-- 幂等 additive,不动 status 列(自由文本 String(20),paused 直接写入)。
ALTER TABLE aihelms.crawl_tasks
    ADD COLUMN IF NOT EXISTS paused_from VARCHAR(20);
