-- 048_document_api_incremental_extract.sql
-- 增量提取：记录提取时文档内容 hash（DocumentApiSpec.content_hash），
-- 批量任务统计跳过未变更文档数（document_api_batch_jobs.skipped_documents）。
-- additive-only, idempotent。

-- ─── DocumentApiSpec 记录提取时文档 content_hash ─────────────────────────────
ALTER TABLE aihelms.document_api_specs
    ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64) NOT NULL DEFAULT '';

-- ─── 批量提取任务加跳过计数 ───────────────────────────────────────────────────
ALTER TABLE aihelms.document_api_batch_jobs
    ADD COLUMN IF NOT EXISTS skipped_documents INT NOT NULL DEFAULT 0;
