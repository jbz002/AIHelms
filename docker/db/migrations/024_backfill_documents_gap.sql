-- 024: 补回 023 之后、本次代码修复之前产生的 crawl/upload 行缺失的 documents 记录
-- 023 是一次性回填；023 跑过之后新产生的爬取/上传因代码 bug 未写 documents。
-- 本次代码修复后，新爬取/上传会在内容可用时即写 documents(pending)。
-- 本迁移用 NOT EXISTS 保证幂等，可安全重复执行。

-- 1. 爬取页面：缺 documents 行的补齐（状态按 crawled_pages.ingest_status 映射）
INSERT INTO aihelms.documents (
    title, content, library, version, source_type, source_id,
    chunk_count, ingest_status, content_hash, created_by, created_at, metadata
)
SELECT
    COALESCE(cp.title, cp.url),
    cp.text_content,
    ct.library,
    ct.version,
    'crawl',
    cp.id,
    COALESCE(jsonb_array_length(cp.chunks), 0),
    CASE
        WHEN cp.ingest_status = 'ingested' THEN 'ingested'
        WHEN cp.ingest_status = 'failed' THEN 'failed'
        ELSE 'pending'
    END,
    '',
    ct.created_by,
    cp.created_at,
    jsonb_build_object('url', cp.url, 'crawl_task_id', cp.crawl_task_id, 'depth', cp.depth)
FROM aihelms.crawled_pages cp
JOIN aihelms.crawl_tasks ct ON cp.crawl_task_id = ct.id
WHERE cp.text_content IS NOT NULL AND cp.text_content != ''
  AND NOT EXISTS (
      SELECT 1 FROM aihelms.documents d
      WHERE d.source_type = 'crawl' AND d.source_id = cp.id
  );

-- 2. 上传记录：缺 documents 行的补齐（状态按 doc_upload_records.status 映射）
INSERT INTO aihelms.documents (
    title, content, library, version, source_type, source_id,
    chunk_count, ingest_status, content_hash, error_message,
    created_by, created_at, metadata
)
SELECT
    dur.file_name,
    dur.extracted_content,
    dur.library,
    dur.version,
    'upload',
    dur.id,
    dur.chunk_count,
    CASE
        WHEN dur.status = 'completed' THEN 'ingested'
        WHEN dur.status = 'failed' THEN 'failed'
        WHEN dur.status = 'extracted' THEN 'pending'
        ELSE dur.status
    END,
    '',
    dur.error_message,
    dur.created_by,
    dur.created_at,
    jsonb_build_object('file_name', dur.file_name, 'content_type', dur.content_type, 'file_size', dur.file_size)
FROM aihelms.doc_upload_records dur
WHERE dur.extracted_content IS NOT NULL AND dur.extracted_content != ''
  AND NOT EXISTS (
      SELECT 1 FROM aihelms.documents d
      WHERE d.source_type = 'upload' AND d.source_id = dur.id
  );
