-- 059: document_libraries 增加 active_version 列，平台侧记录「生效版本」。
-- 生效口径=active 优先，为空时检索/列表回退最新 semver（docs-mcp best-match）。
-- 仅加列；现有 version='' 数据由 dev/migrate-doc-versions 脚本搬迁到 1.0.0 并回填本列。
-- 幂等：IF NOT EXISTS；附加式，不动既有列。

ALTER TABLE aihelms.document_libraries
    ADD COLUMN IF NOT EXISTS active_version VARCHAR(200) NOT NULL DEFAULT '';
