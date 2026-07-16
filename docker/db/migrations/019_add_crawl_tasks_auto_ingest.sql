-- crawl_tasks 新增 auto_ingest 字段，支持爬取完成后自动入库
ALTER TABLE aihelms.crawl_tasks ADD COLUMN IF NOT EXISTS auto_ingest BOOLEAN NOT NULL DEFAULT FALSE;
