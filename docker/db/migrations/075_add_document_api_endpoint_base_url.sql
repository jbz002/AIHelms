-- 文档级 base_url:AI 提取接口时一并提取,落每条 endpoint(同文档同值)。
-- TryItOut 调试默认值,取代旧的"全库共享 baseurl" localStorage 机制。
ALTER TABLE aihelms.document_api_endpoints
    ADD COLUMN IF NOT EXISTS base_url TEXT NOT NULL DEFAULT '';
