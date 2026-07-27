-- 046_create_document_api_extraction.sql
-- AI 接口提取：异步任务表 + 结构化接口表（source of truth，核心字段独立列）。
-- additive-only, idempotent。仿 022（表 + trigger）+ 037（权限码）。

-- ─── 提取任务表（仿 ai_policies_audits：queued/running/completed/failed）─────────
CREATE TABLE IF NOT EXISTS aihelms.document_api_specs (
    id BIGSERIAL PRIMARY KEY,
    spec_id VARCHAR(64) NOT NULL UNIQUE,
    document_id BIGINT NOT NULL REFERENCES aihelms.documents(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    model_id BIGINT REFERENCES aihelms.models(id) ON DELETE SET NULL,
    model_name VARCHAR(200) NOT NULL DEFAULT '',
    endpoint_count INT NOT NULL DEFAULT 0,
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    summary JSONB NOT NULL DEFAULT '{}',
    raw_output JSONB NOT NULL DEFAULT '{}',
    error_message TEXT NOT NULL DEFAULT '',
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_api_specs_document_id
    ON aihelms.document_api_specs(document_id);
CREATE INDEX IF NOT EXISTS idx_document_api_specs_status
    ON aihelms.document_api_specs(status);

CREATE TRIGGER trg_document_api_specs_updated_at
    BEFORE UPDATE ON aihelms.document_api_specs
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();

-- ─── 结构化接口表（source of truth：method/path 等核心字段为独立列，非 JSONB）─────
CREATE TABLE IF NOT EXISTS aihelms.document_api_endpoints (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES aihelms.documents(id) ON DELETE CASCADE,
    method VARCHAR(10) NOT NULL,
    path VARCHAR(500) NOT NULL,
    summary VARCHAR(500) NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    operation_id VARCHAR(200) NOT NULL DEFAULT '',
    tags JSONB NOT NULL DEFAULT '[]',
    parameters JSONB NOT NULL DEFAULT '[]',
    request_body JSONB NOT NULL DEFAULT '{}',
    responses JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_document_api_endpoints_doc_method_path
        UNIQUE (document_id, method, path)
);

CREATE INDEX IF NOT EXISTS idx_document_api_endpoints_document_id
    ON aihelms.document_api_endpoints(document_id);

CREATE TRIGGER trg_document_api_endpoints_updated_at
    BEFORE UPDATE ON aihelms.document_api_endpoints
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();

-- ─── 权限码注册（仿 037）──────────────────────────────────────────────────────
INSERT INTO aihelms.permissions (code, name, resource, action, description) VALUES
    ('document:extract', '提取文档接口', 'document', 'extract', 'AI 提取文档中的 API 接口')
ON CONFLICT (code) DO NOTHING;

-- 038 历史回填已跑，新权限码需显式授予 super_admin/admin（仅注册不自动到位）
INSERT INTO aihelms.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM aihelms.roles r, aihelms.permissions p
WHERE r.name IN ('super_admin', 'admin')
  AND p.code = 'document:extract'
ON CONFLICT (role_id, permission_id) DO NOTHING;
