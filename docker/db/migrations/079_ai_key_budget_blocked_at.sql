-- 079: 预算硬阻断状态列，记录 key 被聚合任务卡住的时间（NULL=未阻断）
ALTER TABLE aihelms.ai_keys
    ADD COLUMN IF NOT EXISTS budget_blocked_at TIMESTAMPTZ;
