-- 022: 文档知识库注册表 + 统一文档表（自主数据层）

-- 文档知识库注册表：平台侧记录所有知识库，与 docs-mcp-server 的 libraries 对齐
CREATE TABLE IF NOT EXISTS aihelms.document_libraries (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description VARCHAR(500) NOT NULL DEFAULT '',
    document_count INT NOT NULL DEFAULT 0,
    total_chunks INT NOT NULL DEFAULT 0,
    source_url TEXT NOT NULL DEFAULT '',
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_document_libraries_name_lower
    ON aihelms.document_libraries(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_document_libraries_created_by
    ON aihelms.document_libraries(created_by);

CREATE TRIGGER trg_document_libraries_updated_at
    BEFORE UPDATE ON aihelms.document_libraries
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();

-- 统一文档表：合并上传和爬取两种来源的文档内容，为后续 CRUD 铺路
CREATE TABLE IF NOT EXISTS aihelms.documents (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    library VARCHAR(200) NOT NULL,
    version VARCHAR(200) NOT NULL DEFAULT '',
    source_type VARCHAR(20) NOT NULL,
    source_id BIGINT,
    chunk_count INT NOT NULL DEFAULT 0,
    ingest_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_documents_library_version ON aihelms.documents(library, version);
CREATE INDEX IF NOT EXISTS idx_documents_source ON aihelms.documents(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_documents_ingest_status ON aihelms.documents(ingest_status);
CREATE INDEX IF NOT EXISTS idx_documents_created_by ON aihelms.documents(created_by);
CREATE INDEX IF NOT EXISTS idx_documents_library ON aihelms.documents(library);

CREATE TRIGGER trg_documents_updated_at
    BEFORE UPDATE ON aihelms.documents
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();
