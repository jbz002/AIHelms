-- S8 · 内置 Skills 开箱即用
--   skills 加 is_builtin / builtin_slug：结构化内置标记（幂等键 + 内置列表查询 + UI 徽标）。
--   不依赖 official Label（手动可撤销的运营标签）作唯一标识，遵循「关键字段独立列」红线。
--   内置 skill 仍照常授予 official Label（S4）。
-- idempotent / additive-only。

ALTER TABLE aihelms.skills
    ADD COLUMN IF NOT EXISTS is_builtin   BOOLEAN     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS builtin_slug VARCHAR(64) NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_skills_builtin_slug
    ON aihelms.skills(builtin_slug) WHERE is_builtin = true;
