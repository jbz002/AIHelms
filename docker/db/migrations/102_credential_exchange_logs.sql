-- P2-F4 Token Broker：换票审计。每次 /mcp/credentials/exchange 落一行。
-- 只记主体、目标、结果码与耗时，**不记委托票本身**（02 §7 日志红线）。

CREATE TABLE IF NOT EXISTS aihelms.credential_exchange_logs (
    id           BIGSERIAL PRIMARY KEY,
    subject_type VARCHAR(20)  NOT NULL,
    subject_id   VARCHAR(64)  NOT NULL,
    actor_kind   VARCHAR(20)  NOT NULL DEFAULT 'human',
    target       VARCHAR(64)  NOT NULL,
    provider     VARCHAR(32)  NOT NULL DEFAULT 'quanyu',
    result       VARCHAR(10)  NOT NULL,
    reason_code  VARCHAR(64)  NOT NULL,
    cached       BOOLEAN      NOT NULL DEFAULT FALSE,
    expires_in   INTEGER      NULL,
    latency_ms   INTEGER      NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_credential_result CHECK (result IN ('allow', 'deny'))
);

COMMENT ON TABLE aihelms.credential_exchange_logs IS
    'Token Broker 换票审计：只记主体/目标/结果码，不记票';

CREATE INDEX IF NOT EXISTS idx_credential_created
    ON aihelms.credential_exchange_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_credential_subject
    ON aihelms.credential_exchange_logs (subject_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_credential_target
    ON aihelms.credential_exchange_logs (target, created_at DESC);
