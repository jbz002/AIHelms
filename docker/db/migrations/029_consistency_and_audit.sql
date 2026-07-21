-- 029: 一致性保障与审计强化（模块 S6 一致性与审计强化）
-- additive-only, idempotent。不动既有列。
-- 幂等记录表：Idempotency-Key + request_hash 命中返回首次响应，防重复提交。
-- 存储删除补偿表：DB 提交后删文件失败 → 补偿记录，定时重试，避免孤儿文件。
-- lock_version：关键实体乐观锁计数器，update where lock_version=expected 防并发覆盖。
-- admin_audit_logs：补 request_id（链路追踪）+ detail（结构化扩展 JSONB）。

-- 幂等记录表
CREATE TABLE IF NOT EXISTS aihelms.idempotency_records (
    id BIGSERIAL PRIMARY KEY,
    key VARCHAR(128) NOT NULL UNIQUE,
    entity_type VARCHAR(32) NOT NULL,
    entity_id BIGINT,
    request_hash VARCHAR(64) NOT NULL,
    response_code SMALLINT,
    response_body JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON aihelms.idempotency_records(expires_at);

-- 存储删除补偿表
CREATE TABLE IF NOT EXISTS aihelms.storage_deletion_compensations (
    id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(32) NOT NULL,
    entity_id BIGINT,
    storage_path TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending / done / failed
    retries INTEGER NOT NULL DEFAULT 0,
    last_error TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_storage_comp_status
    ON aihelms.storage_deletion_compensations(status, created_at);

-- 乐观锁计数器（关键实体）
ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE aihelms.resource_applications
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE aihelms.entity_ratings
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;

-- 审计日志：request_id 链路追踪 + detail 结构化扩展
ALTER TABLE aihelms.admin_audit_logs
    ADD COLUMN IF NOT EXISTS request_id VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS detail JSONB NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_audit_logs_request_id
    ON aihelms.admin_audit_logs(request_id) WHERE request_id <> '';
