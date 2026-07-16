-- crawled_pages 新增入库状态列，支持按页幂等重试入库
ALTER TABLE aihelms.crawled_pages ADD COLUMN IF NOT EXISTS ingest_status VARCHAR(20) NOT NULL DEFAULT 'pending';
CREATE INDEX IF NOT EXISTS idx_crawled_pages_ingest_status ON aihelms.crawled_pages(ingest_status);
