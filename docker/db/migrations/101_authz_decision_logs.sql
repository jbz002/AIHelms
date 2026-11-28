-- P2 PDP：授权决策日志。每次 /mcp/authorize 落一行（allow 与 deny 都记）。
-- 只记标识与判定结果，不记工具入参与业务返回体（02 §7 日志红线）。

CREATE TABLE IF NOT EXISTS aihelms.authz_decision_logs (
    id                       BIGSERIAL PRIMARY KEY,
    subject_type             VARCHAR(20)  NOT NULL,
    subject_id               BIGINT       NULL,
    actor_kind               VARCHAR(20)  NOT NULL,
    actor_service_account_id BIGINT       NULL,
    server_name              VARCHAR(128) NOT NULL,
    tool_name                VARCHAR(200) NULL,
    tool_key                 VARCHAR(200) NULL,
    decision                 VARCHAR(10)  NOT NULL,
    reason_code              VARCHAR(64)  NOT NULL,
    policy_version           BIGINT       NULL,
    trace_id                 VARCHAR(64)  NULL,
    latency_ms               INTEGER      NULL,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_decision CHECK (decision IN ('allow', 'deny'))
);

COMMENT ON TABLE aihelms.authz_decision_logs IS
    'PDP 决策日志：subject 是数据主体，actor 是实际执行者（human / service）';

CREATE INDEX IF NOT EXISTS idx_decision_created
    ON aihelms.authz_decision_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_subject
    ON aihelms.authz_decision_logs (subject_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_server
    ON aihelms.authz_decision_logs (server_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_reason
    ON aihelms.authz_decision_logs (reason_code, created_at DESC);

-- 机器代人类的总闸：默认关闭，按 server 显式开启。
-- 有效权限 = 用户授权 ∩ 委托范围 ∩ 本开关（02 §6）。
ALTER TABLE aihelms.mcp_servers
    ADD COLUMN IF NOT EXISTS allow_machine_delegation BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN aihelms.mcp_servers.allow_machine_delegation IS
    '是否允许服务账号代人类调用本 server；默认 false（fail-closed）';
