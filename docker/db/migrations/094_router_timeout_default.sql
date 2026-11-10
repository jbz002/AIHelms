-- 094: 路由超时默认值 30s → 600s
-- 背景：平台 router_settings.timeout 一直通过已废弃的 POST /router/settings 下发，
-- 在 LiteLLM v1.103 上返回 405，从未真正生效；本次改为经 /config/update 持久化。
-- LiteLLM 的流式请求在没有单独 stream_timeout 时会复用该 timeout，
-- 30s 会让长思考/长工具调用中断，故默认值调到 600s。
-- 幂等：ALTER DEFAULT 可重复执行；UPDATE 仅命中仍为旧默认值的行，重复执行 no-op。

ALTER TABLE aihelms.router_settings
    ALTER COLUMN timeout SET DEFAULT 600;

UPDATE aihelms.router_settings
SET timeout = 600
WHERE timeout = 30;
