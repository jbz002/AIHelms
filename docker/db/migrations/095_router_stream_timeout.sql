-- 095: 路由流式超时独立配置（router_settings.stream_timeout）
-- 背景：LiteLLM v1.103 支持 router_settings.stream_timeout；未设置时流式请求
-- 会复用 timeout（094 已调到 600s），长思考/长工具调用仍可能被截断。
-- 本次把流式总超时独立为 1800s，并纳入 /config/update 下发（重启后生效）。
-- 幂等：ADD COLUMN IF NOT EXISTS 可重复执行；UPDATE 只补 NULL 行。

ALTER TABLE aihelms.router_settings
    ADD COLUMN IF NOT EXISTS stream_timeout INT DEFAULT 1800;

UPDATE aihelms.router_settings
SET stream_timeout = 1800
WHERE stream_timeout IS NULL;
