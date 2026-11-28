-- 098: MCP 授权中心（P1）——工具元数据 / 授权矩阵 / 工具束 / 编译状态 / 策略版本
--
-- 背景：P0 把「谁有哪些 server」写进了 ai_keys.mcps 并下发给网关，但没有唯一事实源，
-- 也没法表达工具级、角色/部门级、deny 与过期。P1 引入：
--   mcp_grants      授权矩阵（唯一事实源，subject × target × effect）
--   mcp_toolsets    跨 server 的工具束（「采购只读」这类）
--   mcp_sync_state  每把 key 的编译/下发状态（幂等 + 漂移可见）
--   mcp_policy_versions 策略版本（决策日志与撤销比对用）
-- ai_keys.mcps 继续保留，语义变为「编译产物」（个人直接授权 + 角色/部门授权的物化）。
--
-- 幂等：IF NOT EXISTS 全量可重复执行。

-- ── 1. 工具元数据 ────────────────────────────────────────────────────────────
ALTER TABLE aihelms.mcp_tools
    ADD COLUMN IF NOT EXISTS tool_key VARCHAR(300),
    ADD COLUMN IF NOT EXISTS risk_level VARCHAR(16) NOT NULL DEFAULT 'read',
    ADD COLUMN IF NOT EXISTS data_classification VARCHAR(16) NOT NULL DEFAULT 'internal',
    ADD COLUMN IF NOT EXISTS permission_key VARCHAR(100),
    ADD COLUMN IF NOT EXISTS annotations JSONB,
    ADD COLUMN IF NOT EXISTS output_schema JSONB,
    ADD COLUMN IF NOT EXISTS fields_allowlist JSONB,
    ADD COLUMN IF NOT EXISTS schema_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(16) NOT NULL DEFAULT 'approved',
    ADD COLUMN IF NOT EXISTS reviewed_by BIGINT,
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

-- 存量工具：稳定键 = server_name.tool_name；默认已过审（不改变现网行为）
UPDATE aihelms.mcp_tools t
   SET tool_key = s.server_name || '.' || t.tool_name
  FROM aihelms.mcp_servers s
 WHERE s.id = t.server_id
   AND t.tool_key IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_tools_tool_key
    ON aihelms.mcp_tools (tool_key)
    WHERE tool_key IS NOT NULL;

-- ── 2. ai_keys 编译产物 ──────────────────────────────────────────────────────
ALTER TABLE aihelms.ai_keys
    ADD COLUMN IF NOT EXISTS mcp_tools JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS mcp_toolsets JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS mcp_policy_hash VARCHAR(64);

-- ── 3. 授权矩阵 ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aihelms.mcp_grants (
    id BIGSERIAL PRIMARY KEY,
    subject_type VARCHAR(20) NOT NULL,
    subject_id BIGINT,
    target_type VARCHAR(20) NOT NULL,
    target_id BIGINT NOT NULL,
    effect VARCHAR(10) NOT NULL DEFAULT 'allow',
    expires_at TIMESTAMPTZ,
    granted_by BIGINT,
    reason TEXT,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_mcp_grants_subject CHECK (
        (subject_type = 'public' AND subject_id IS NULL)
        OR (subject_type IN ('user', 'dept', 'role') AND subject_id IS NOT NULL)
    ),
    CONSTRAINT ck_mcp_grants_target CHECK (target_type IN ('server', 'toolset')),
    CONSTRAINT ck_mcp_grants_effect CHECK (effect IN ('allow', 'deny'))
);

-- 同一主体对同一目标只允许一条未撤销记录（改授权 = 撤销旧的 + 新建）
CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_grants_active
    ON aihelms.mcp_grants (
        subject_type, COALESCE(subject_id, 0), target_type, target_id
    )
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_grants_subject
    ON aihelms.mcp_grants (subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_mcp_grants_target
    ON aihelms.mcp_grants (target_type, target_id);

-- ── 4. 工具束 ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aihelms.mcp_toolsets (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 5. 每把 key 的编译/下发状态 ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aihelms.mcp_sync_state (
    ai_key_id BIGINT PRIMARY KEY REFERENCES aihelms.ai_keys(id) ON DELETE CASCADE,
    input_hash VARCHAR(64),
    applied_hash VARCHAR(64),
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    error_code VARCHAR(64),
    synced_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 6. 策略版本 ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aihelms.mcp_policy_versions (
    id BIGSERIAL PRIMARY KEY,
    version BIGINT NOT NULL,
    changed_by BIGINT,
    change_summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO aihelms.mcp_policy_versions (version, changed_by, change_summary)
SELECT 1, NULL, 'P1 授权中心初始化'
WHERE NOT EXISTS (SELECT 1 FROM aihelms.mcp_policy_versions);
