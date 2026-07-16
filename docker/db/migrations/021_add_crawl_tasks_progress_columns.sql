-- crawl_tasks: 追踪当前爬取 URL（实时进度展示）和入库进度计数
ALTER TABLE aihelms.crawl_tasks ADD COLUMN IF NOT EXISTS current_url TEXT NOT NULL DEFAULT '';
ALTER TABLE aihelms.crawl_tasks ADD COLUMN IF NOT EXISTS pages_ingested INTEGER NOT NULL DEFAULT 0;
