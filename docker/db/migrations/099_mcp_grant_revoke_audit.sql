-- P1 收口：授权撤销的操作人。
-- 之前撤销只记时间（revoked_at），查不到「谁撤的」，不满足验收门
-- 「每一次授权变更都能查到操作人、前后值、时间」。
ALTER TABLE aihelms.mcp_grants
    ADD COLUMN IF NOT EXISTS revoked_by BIGINT;

COMMENT ON COLUMN aihelms.mcp_grants.revoked_by IS
    '撤销操作的用户 ID（granted_by 是授予人；两者都为空表示由脚本/迁移写入）';
