-- 047_document_api_category_and_library_jobs.sql
-- 接口分类列 + 库级批量提取/分类任务表。additive-only, idempotent。
-- 仿 046（表 + trigger + 权限码）。

-- ─── DocumentApiEndpoint 加 category 列（AI 业务模块分类，核心字段独立列）─────
ALTER TABLE aihelms.document_api_endpoints
    ADD COLUMN IF NOT EXISTS category VARCHAR(200) NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_document_api_endpoints_category
    ON aihelms.document_api_endpoints(category);

-- ─── 库级批量提取任务表（顺序处理库内每个 ingested 文档）─────────────────────
CREATE TABLE IF NOT EXISTS aihelms.document_api_batch_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL UNIQUE,
    library VARCHAR(200) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    model_id BIGINT REFERENCES aihelms.models(id) ON DELETE SET NULL,
    model_name VARCHAR(200) NOT NULL DEFAULT '',
    total_documents INT NOT NULL DEFAULT 0,
    completed_documents INT NOT NULL DEFAULT 0,
    failed_documents INT NOT NULL DEFAULT 0,
    total_endpoints INT NOT NULL DEFAULT 0,
    summary JSONB NOT NULL DEFAULT '{}',
    error_message TEXT NOT NULL DEFAULT '',
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_api_batch_jobs_library
    ON aihelms.document_api_batch_jobs(library);
CREATE INDEX IF NOT EXISTS idx_document_api_batch_jobs_status
    ON aihelms.document_api_batch_jobs(status);

CREATE TRIGGER trg_document_api_batch_jobs_updated_at
    BEFORE UPDATE ON aihelms.document_api_batch_jobs
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();

-- ─── 库级 AI 分类任务表 ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aihelms.document_api_category_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL UNIQUE,
    library VARCHAR(200) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    model_id BIGINT REFERENCES aihelms.models(id) ON DELETE SET NULL,
    model_name VARCHAR(200) NOT NULL DEFAULT '',
    endpoint_count INT NOT NULL DEFAULT 0,
    category_count INT NOT NULL DEFAULT 0,
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    categories JSONB NOT NULL DEFAULT '[]',
    raw_output JSONB NOT NULL DEFAULT '{}',
    summary JSONB NOT NULL DEFAULT '{}',
    error_message TEXT NOT NULL DEFAULT '',
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_api_category_jobs_library
    ON aihelms.document_api_category_jobs(library);
CREATE INDEX IF NOT EXISTS idx_document_api_category_jobs_status
    ON aihelms.document_api_category_jobs(status);

CREATE TRIGGER trg_document_api_category_jobs_updated_at
    BEFORE UPDATE ON aihelms.document_api_category_jobs
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();

-- ─── 权限码注册（仿 046 line 62-72）─────────────────────────────────────────
INSERT INTO aihelms.permissions (code, name, resource, action, description) VALUES
    ('document:batch_extract', '批量提取库接口', 'document', 'batch_extract', '批量提取库内已入库文档的 API 接口'),
    ('document:classify', '分类库接口', 'document', 'classify', 'AI 按业务模块对库内接口分类')
ON CONFLICT (code) DO NOTHING;

-- 新权限码需显式授予 super_admin/admin（仅注册不自动到位）
INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM aihelms.roles r, aihelms.permissions p
WHERE r.name IN ('super_admin', 'admin')
  AND p.code IN ('document:batch_extract', 'document:classify')
ON CONFLICT (role_id, permission_id) DO NOTHING;
