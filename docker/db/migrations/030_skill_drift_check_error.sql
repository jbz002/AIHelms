-- 030: S9 漂移检测落地 — 拉取失败原因列 + 活跃 url 版本扫描索引
-- additive-only, idempotent。不动既有列。
-- drift_check_error：拉取/SSRF/包校验失败时记录原因，admin 可见；失败不标 drift（语义不污染）。
-- idx_skill_versions_drift_scan：定时任务扫描 source_type='url' AND lifecycle_status='active' 加速。

ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS drift_check_error TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_skill_versions_drift_scan
    ON aihelms.skill_versions(source_type, lifecycle_status)
    WHERE source_type = 'url' AND lifecycle_status = 'active';
