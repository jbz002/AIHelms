-- 096: MCP 目录登记开关（catalog-only）
-- 背景：钉钉 OAuth 类 MCP 按人授权（token 在消费端 LibreChat），数据面不能也不应
-- 经 LiteLLM 网关委托。平台需要「仅目录登记、不同步 LiteLLM」的形态：
-- 市场可见（发现层），调用面仍在消费端。
-- 幂等：IF NOT EXISTS 可重复执行；存量行默认 TRUE 保持现行为。

ALTER TABLE aihelms.mcp_servers
    ADD COLUMN IF NOT EXISTS sync_to_litellm BOOLEAN NOT NULL DEFAULT TRUE;
