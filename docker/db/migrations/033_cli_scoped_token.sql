-- S7 阶段一 · CLI 分发通道 Scoped Token
--   ai_keys 复用加列：token_kind(llm|cli 判别) / token_hash(sha256) / token_prefix(展示) / scope_json(分权)
--   CLI token 行 litellm_key_id 为 NULL，与 LLM 明文 key 隔离；token_kind 路由判别。
--   last_used_at 已存在，不重复加。
-- idempotent / additive-only。

ALTER TABLE aihelms.ai_keys
    ADD COLUMN IF NOT EXISTS token_kind   VARCHAR(20) NOT NULL DEFAULT 'llm',  -- 'llm' | 'cli'
    ADD COLUMN IF NOT EXISTS token_hash   VARCHAR(64) NOT NULL DEFAULT '',     -- sha256(full_token)，仅 cli 行
    ADD COLUMN IF NOT EXISTS token_prefix VARCHAR(16) NOT NULL DEFAULT '',     -- 展示用前缀（不敏感）
    ADD COLUMN IF NOT EXISTS scope_json   JSONB      NOT NULL DEFAULT '[]';    -- ['skill:search', ...]

CREATE INDEX IF NOT EXISTS idx_ai_keys_token_hash
    ON aihelms.ai_keys(token_hash) WHERE token_kind = 'cli';

-- CLI 令牌管理权限（镜像 api_key:* 四码）
INSERT INTO aihelms.permissions (code, name, resource, action, description) VALUES
    ('cli_token:create', '创建 CLI 令牌', 'cli_token', 'create', '创建 CLI 分发令牌'),
    ('cli_token:read',   '查看 CLI 令牌', 'cli_token', 'read',   '查看 CLI 令牌列表和详情'),
    ('cli_token:update', '编辑 CLI 令牌', 'cli_token', 'update', '启用/禁用、修改 CLI 令牌 scope'),
    ('cli_token:delete', '撤销 CLI 令牌', 'cli_token', 'delete', '撤销 CLI 令牌')
ON CONFLICT (code) DO NOTHING;
