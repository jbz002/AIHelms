-- 052: documents 表增加 ingest_url 列，锁死入库时提交给 docs-mcp 的 url。
-- 删除单文档时按该 url 精确定位 docs-mcp 中的 page，删除其全部向量。
-- 幂等：IF NOT EXISTS；backfill 用旧口径重算，匹配历史已入库的 page.url。

ALTER TABLE aihelms.documents
    ADD COLUMN IF NOT EXISTS ingest_url TEXT NOT NULL DEFAULT '';

UPDATE aihelms.documents SET ingest_url = CASE
    WHEN source_type = 'crawl'
         AND metadata->>'url' IS NOT NULL
         AND metadata->>'url' <> '' THEN metadata->>'url'
    WHEN source_type = 'upload'
         AND metadata->>'file_name' IS NOT NULL
         AND metadata->>'file_name' <> '' THEN 'local://' || (metadata->>'file_name')
    ELSE 'aihelms://document/' || id::text
END WHERE ingest_url = '';
