-- 097: MCP 公共授权开关（is_public / public_reason）
--
-- 背景：LiteLLM 的 allow_all_keys 曾由平台对所有 server 无条件置 TRUE，效果是
-- 「任意有效 key 可调任意已注册 server」，key 侧的 object_permission 形同虚设。
-- 改为按 server 显式标记：只有 is_public=TRUE 的 server 继续全员开放（公共只读
-- 目录类），其余全靠 key 的 object_permission.mcp_servers 授权。
--
-- 存量：docs_mcp_server 是全员可用的只读文档检索（现网既有事实），保持公共；
-- 业务 server（supply_cloud / product_order）由
-- scripts/backfill_key_mcp_permissions.py 按 ai_keys.mcps 逐 key 授权后，
-- 再切换 allow_all_keys 才会真正收口（见 docs/MCP鉴权增强方案/04）。
--
-- 幂等：IF NOT EXISTS 可重复执行；UPDATE 只命中尚未标记的 docs 行。

ALTER TABLE aihelms.mcp_servers
    ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS public_reason TEXT;

UPDATE aihelms.mcp_servers
   SET is_public = TRUE,
       public_reason = COALESCE(public_reason, '存量公共只读：文档检索对全员开放')
 WHERE server_name = 'docs_mcp_server'
   AND is_public = FALSE;
