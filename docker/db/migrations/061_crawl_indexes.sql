-- 061: 爬虫入库与文档去重的复合索引补齐
-- crawled_pages.get_for_ingest 过滤 (crawl_task_id, ingest_status)，
--   原仅有两个单列索引，大任务下回表代价高 → 加复合索引覆盖。
-- documents.find_duplicate_by_hash 过滤 (LOWER(library), version, content_hash, ingest_status)，
--   content_hash 原无索引 → 加 (library, version, content_hash) 复合索引。
-- 幂等：IF NOT EXISTS；附加式，不动既有列/索引。

CREATE INDEX IF NOT EXISTS idx_crawled_pages_task_ingest
  ON aihelms.crawled_pages (crawl_task_id, ingest_status);

CREATE INDEX IF NOT EXISTS idx_documents_lib_ver_hash
  ON aihelms.documents (library, version, content_hash);
