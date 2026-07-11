-- MCP 版本管理：每个 MCP Server 的多版本运行时快照 + 版本元信息
-- 设计：主表 mcp_servers 存「跨版本稳定元数据 + 当前 active 版本指针 + active 版本运行时冗余快照」；
--       子表 mcp_server_versions 存每个版本的运行时配置快照与生命周期状态。
-- LiteLLM 侧每个逻辑 Server 永远只持有 active 版本配置（单 active 路由）。

-- 1. 版本子表（mcp_servers 已存在，server_id 外键可直接声明）
CREATE TABLE IF NOT EXISTS aihelms.mcp_server_versions (
    id BIGSERIAL PRIMARY KEY,
    server_id BIGINT NOT NULL REFERENCES aihelms.mcp_servers(id) ON DELETE CASCADE,
    version VARCHAR(64) NOT NULL,
    version_label VARCHAR(128) NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT false,
    lifecycle_status VARCHAR(20) NOT NULL DEFAULT 'inactive',
    sunset_date TIMESTAMPTZ,
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
    url TEXT NOT NULL,
    transport VARCHAR(20) NOT NULL,
    auth_type VARCHAR(30) NOT NULL DEFAULT 'none',
    credentials JSONB NOT NULL DEFAULT '{}',
    mcp_info JSONB NOT NULL DEFAULT '{}',
    allowed_tools JSONB NOT NULL DEFAULT '[]',
    extra_headers TEXT[] NOT NULL DEFAULT '{}',
    instructions TEXT NOT NULL DEFAULT '',
    auto_discovered_version VARCHAR(64) NOT NULL DEFAULT '',
    change_log TEXT NOT NULL DEFAULT '',
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(server_id, version)
);

CREATE INDEX IF NOT EXISTS idx_mcp_server_versions_server
    ON aihelms.mcp_server_versions(server_id);
-- 每个逻辑 Server 至多 1 个 active（部分唯一索引，DB 层保证单 active 不变式）
CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_server_versions_active
    ON aihelms.mcp_server_versions(server_id) WHERE is_active = true;

-- 2. 主表加 active 版本指针（此时 mcp_server_versions 已存在，FK 可内联）
ALTER TABLE aihelms.mcp_servers
    ADD COLUMN IF NOT EXISTS current_version_id BIGINT
    REFERENCES aihelms.mcp_server_versions(id) ON DELETE SET NULL;

-- 3. 存量回填：为每条 mcp_servers 建一条 v1 active 版本（运行时字段从主表拷贝）
INSERT INTO aihelms.mcp_server_versions (
    server_id, version, version_label, is_active, lifecycle_status, source,
    url, transport, auth_type, credentials, mcp_info, allowed_tools, extra_headers,
    instructions, change_log, created_by
)
SELECT
    s.id, '1.0.0', '', true, 'active', 'manual',
    s.url, s.transport, s.auth_type, s.credentials, s.mcp_info, s.allowed_tools,
    s.extra_headers, s.instructions, 'backfill from existing record', s.created_by
FROM aihelms.mcp_servers s
WHERE NOT EXISTS (
    SELECT 1 FROM aihelms.mcp_server_versions v WHERE v.server_id = s.id
);

-- 4. 回填 current_version_id 指针指向各自的 active 版本
UPDATE aihelms.mcp_servers s
SET current_version_id = (
    SELECT v.id FROM aihelms.mcp_server_versions v
    WHERE v.server_id = s.id AND v.is_active = true
    LIMIT 1
)
WHERE s.current_version_id IS NULL;
