-- 028: AI Policies S2 — verdict/policy/scan_round/soft-delete（模块 S2 安全扫描深化）
-- additive-only, idempotent。不动既有列。
-- verdict: 4 级聚合结果 SAFE/SUSPICIOUS/DANGEROUS/BLOCKED，映射到现有 decision，激活门控不改。
-- policy: 创建审查时冻结的策略名 strict/balanced/permissive。
-- scan_round: 同 skill+version 的扫描轮次递增，支撑多轮历史时间线。
-- deleted_at: 版本/ Skill 物理删除时审计行 soft-delete 保留（审计合规）。

ALTER TABLE aihelms.ai_policies_audits
    ADD COLUMN IF NOT EXISTS verdict VARCHAR(16) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS policy VARCHAR(32) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS scan_round INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ai_policies_audits_skill_version_round
    ON aihelms.ai_policies_audits(skill_id, skill_version_id, scan_round DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_ai_policies_audits_verdict
    ON aihelms.ai_policies_audits(verdict) WHERE verdict <> '';

ALTER TABLE aihelms.ai_policies_settings
    ADD COLUMN IF NOT EXISTS default_policy VARCHAR(32) NOT NULL DEFAULT 'balanced',
    ADD COLUMN IF NOT EXISTS policy_overrides JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS llm_consensus_runs INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS regex_enabled BOOLEAN NOT NULL DEFAULT true;

-- 旧 audit 回填 verdict（由 decision 反推，保证前端旧报告也有 4 级徽标）
UPDATE aihelms.ai_policies_audits
SET verdict = CASE decision
    WHEN 'passed' THEN 'SAFE'
    WHEN 'attention_required' THEN 'SUSPICIOUS'
    WHEN 'high_risk' THEN 'DANGEROUS'
    WHEN 'failed' THEN 'BLOCKED'
    ELSE 'SAFE' END
WHERE verdict = '' AND decision <> '' AND status = 'completed';
