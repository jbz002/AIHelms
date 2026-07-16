-- 023: 从现有表回填 document_libraries 和 documents
-- 注：content_hash 回填阶段留空，后续入库流程会自动计算写入

-- 1. 从 crawl_tasks 填充 document_libraries
INSERT INTO aihelms.document_libraries (name, source_url, created_by, created_at, updated_at)
SELECT DISTINCT
    ct.library,
    MIN(ct.source_url),
    MIN(ct.created_by),
    MIN(ct.created_at),
    NOW()
FROM aihelms.crawl_tasks ct
WHERE ct.library IS NOT NULL AND ct.library != ''
GROUP BY ct.library
ON CONFLICT DO NOTHING;

-- 从 doc_upload_records 补充（跳过已存在的）
INSERT INTO aihelms.document_libraries (name, created_by, created_at, updated_at)
SELECT DISTINCT
    dur.library,
    MIN(dur.created_by),
    MIN(dur.created_at),
    NOW()
FROM aihelms.doc_upload_records dur
WHERE dur.library IS NOT NULL AND dur.library != ''
  AND LOWER(dur.library) NOT IN (SELECT LOWER(name) FROM aihelms.document_libraries)
GROUP BY dur.library
ON CONFLICT DO NOTHING;

-- 2. 计算 document_count（上传来源）
UPDATE aihelms.document_libraries dl
SET document_count = sub.cnt
FROM (
    SELECT library, COUNT(*) AS cnt
    FROM aihelms.doc_upload_records
    WHERE extracted_content IS NOT NULL AND extracted_content != ''
    GROUP BY library
) sub
WHERE LOWER(dl.name) = LOWER(sub.library);

-- 加上爬取来源
UPDATE aihelms.document_libraries dl
SET document_count = dl.document_count + sub.cnt
FROM (
    SELECT ct.library, COUNT(cp.id) AS cnt
    FROM aihelms.crawled_pages cp
    JOIN aihelms.crawl_tasks ct ON cp.crawl_task_id = ct.id
    WHERE cp.text_content IS NOT NULL AND cp.text_content != ''
    GROUP BY ct.library
) sub
WHERE LOWER(dl.name) = LOWER(sub.library);

-- 3. 从上传记录填充 documents
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
ON CONFLICT DO NOTHING;

-- 4. 从爬取页面填充 documents
INSERT INTO aihelms.documents (
    title, content, library, version, source_type, source_id,
    ingest_status, content_hash, created_by, created_at, metadata
)
SELECT
    COALESCE(cp.title, cp.url),
    cp.text_content,
    ct.library,
    ct.version,
    'crawl',
    cp.id,
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
ON CONFLICT DO NOTHING;
