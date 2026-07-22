-- 031 · S3 Skill 生命周期状态机精细化
--
-- 把版本生命周期从 3 态（inactive/active/deprecated）升级为覆盖审核流的完整状态机：
--   draft / scanning / pending_review / published / yanked / rejected / deprecated
--
-- 内容：
--   1. skills 加 hidden 治理下架 overlay（独立于 lifecycle_status 与 visibility_type）
--   2. 版本级审核任务表 skill_review_tasks（与实体级 publish_reviews 正交）
--   3. 旧 3 态数据迁移到新状态
--   4. S9 drift 索引谓词 active→published（active 已映射为 published，旧谓词失效）
--
-- 注：第 4 步 DROP INDEX 是对 additive-only 规则的有意偏离——active→published 后
-- 旧部分索引谓词 lifecycle_status='active' 永不命中，S9 漂移扫描静默失效。仅重建索引，无数据丢失。

-- 1. skills 加 hidden overlay
ALTER TABLE aihelms.skills
    ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS hidden_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS hidden_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_skills_hidden
    ON aihelms.skills(hidden) WHERE hidden = true;

-- 2. 版本级审核任务表（保留历史 task；通过部分唯一索引保证一版本仅一个 pending）
CREATE TABLE IF NOT EXISTS aihelms.skill_review_tasks (
    id BIGSERIAL PRIMARY KEY,
    skill_version_id BIGINT NOT NULL REFERENCES aihelms.skill_versions(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',   -- pending / approved / rejected / withdrawn
    reviewer_id BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    submitted_by BIGINT NOT NULL REFERENCES aihelms.users(id) ON DELETE SET NULL,
    decision_notes TEXT NOT NULL DEFAULT '',
    lock_version INTEGER NOT NULL DEFAULT 0,          -- 乐观锁（复用 S6 CAS 模式）
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- 兼容早期硬 UNIQUE 约束（若已建则删除，改用部分唯一索引）
ALTER TABLE aihelms.skill_review_tasks
    DROP CONSTRAINT IF EXISTS uq_skill_review_tasks_version;

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_review_tasks_pending
    ON aihelms.skill_review_tasks(skill_version_id) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_skill_review_tasks_status
    ON aihelms.skill_review_tasks(status);

-- 3. 旧 3 态数据迁移（idempotent：二次执行无行命中）
UPDATE aihelms.skill_versions SET lifecycle_status = 'published'
    WHERE lifecycle_status = 'active';
UPDATE aihelms.skill_versions SET lifecycle_status = 'scanning'
    WHERE lifecycle_status = 'inactive' AND security_status IN ('queued', 'running');
UPDATE aihelms.skill_versions SET lifecycle_status = 'draft'
    WHERE lifecycle_status = 'inactive';

-- 4. S9 drift 索引重建：谓词 active→published
DROP INDEX IF EXISTS aihelms.idx_skill_versions_drift_scan;
CREATE INDEX IF NOT EXISTS idx_skill_versions_drift_scan
    ON aihelms.skill_versions(source_type, lifecycle_status)
    WHERE source_type = 'url' AND lifecycle_status = 'published';
