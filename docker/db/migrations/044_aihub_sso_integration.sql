-- 044: OAuth2 SSO 接入 — 用户表镜像 AI Hub 用户/部门 ID
-- additive-only, idempotent。不动既有列，不影响本地账号登录。
-- aihub_user_id: AI Hub 统一鉴权返回的用户唯一标识（SSO 登录据此 upsert）。
-- aihub_department_id: AI Hub 返回的部门 ID（纯镜像字符串，不建外键，部门只读）。

ALTER TABLE aihelms.users
    ADD COLUMN IF NOT EXISTS aihub_user_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS aihub_department_id VARCHAR(100);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_aihub_user_id
    ON aihelms.users (aihub_user_id) WHERE aihub_user_id IS NOT NULL;
