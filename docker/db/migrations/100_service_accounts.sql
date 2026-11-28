-- P2 身份与委托：服务账号（机器身份）+ 委托授权（人类授权机器代表自己）。
-- 设计：02 §6 / 03 §7。机器自身调用用自己的授权；代表人类必须有未过期的委托，
-- 且执行时取「用户授权 ∩ 委托范围 ∩ server.allow_machine_delegation」。

CREATE TABLE IF NOT EXISTS aihelms.service_accounts (
    id            BIGSERIAL PRIMARY KEY,
    name          VARCHAR(128) NOT NULL UNIQUE,
    kind          VARCHAR(16)  NOT NULL DEFAULT 'bot',
    description   TEXT         NOT NULL DEFAULT '',
    owner_user_id BIGINT       NULL,
    token_prefix  VARCHAR(32)  NOT NULL,
    token_hash    VARCHAR(64)  NOT NULL UNIQUE,
    status        VARCHAR(16)  NOT NULL DEFAULT 'active',
    expires_at    TIMESTAMPTZ  NULL,
    last_used_at  TIMESTAMPTZ  NULL,
    created_by    BIGINT       NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_service_accounts_kind CHECK (kind IN ('bot', 'task', 'agent')),
    CONSTRAINT ck_service_accounts_status CHECK (status IN ('active', 'disabled'))
);

COMMENT ON TABLE aihelms.service_accounts IS
    '机器身份：令牌只存 sha256，明文仅创建/轮换时返回一次';
COMMENT ON COLUMN aihelms.service_accounts.token_prefix IS 'sk_sa_ + 8 hex，展示用';

CREATE TABLE IF NOT EXISTS aihelms.delegation_grants (
    id                 BIGSERIAL PRIMARY KEY,
    service_account_id BIGINT      NOT NULL
        REFERENCES aihelms.service_accounts (id) ON DELETE CASCADE,
    user_id            BIGINT      NOT NULL,
    target_type        VARCHAR(20) NOT NULL DEFAULT 'toolset',
    target_id          BIGINT      NOT NULL,
    expires_at         TIMESTAMPTZ NULL,
    granted_via        VARCHAR(32) NOT NULL DEFAULT 'manual',
    granted_by         BIGINT      NULL,
    reason             TEXT        NULL,
    revoked_at         TIMESTAMPTZ NULL,
    revoked_by         BIGINT      NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_delegation_target_type CHECK (target_type IN ('server', 'toolset'))
);

COMMENT ON TABLE aihelms.delegation_grants IS
    '用户 U 允许服务账号 S 在有效期内在目标（server/toolset）上代表自己';

-- 同一 (服务账号, 用户, 目标) 只允许一条生效记录
CREATE UNIQUE INDEX IF NOT EXISTS uq_delegation_active
    ON aihelms.delegation_grants (service_account_id, user_id, target_type, target_id)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_delegation_sa_user
    ON aihelms.delegation_grants (service_account_id, user_id);
