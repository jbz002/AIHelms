-- 016: 文档上传记录表（API文档管理 - 本地文档入库）

CREATE TABLE IF NOT EXISTS aihelms.doc_upload_records (
    id BIGSERIAL PRIMARY KEY,
    library VARCHAR(200) NOT NULL,
    version VARCHAR(200) DEFAULT '',
    file_name VARCHAR(500) NOT NULL,
    file_size BIGINT NOT NULL DEFAULT 0,
    content_type VARCHAR(100) NOT NULL DEFAULT 'text/plain',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    chunk_count INT DEFAULT 0,
    error_message TEXT DEFAULT '',
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_doc_upload_records_library ON aihelms.doc_upload_records(library);
CREATE INDEX IF NOT EXISTS idx_doc_upload_records_status ON aihelms.doc_upload_records(status);
CREATE INDEX IF NOT EXISTS idx_doc_upload_records_created_by ON aihelms.doc_upload_records(created_by);
