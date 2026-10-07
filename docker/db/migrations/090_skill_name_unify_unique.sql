-- Skill 单名称契约落地：skills.name 对齐 SKILL.md frontmatter name + 全局唯一索引。
-- 背景：name（上传者表单值，可中文）与 frontmatter name（解析后仅存 JSONB）长期双轨，
-- 同一 skill 两个名字；客户端（ai-assistant 等）按 name 字符串判重/溯源全部断链。
-- 终态：name ≡ frontmatter name（kebab），全局唯一；服务层已同步加硬校验
-- （创建 name 以包为准、改名重写 zip + 重算 hash、激活版本 name 回写主表）。

-- 收敛规则（确定性、幂等、绝不失败）：
--   1) frontmatter name 合法（kebab + 无 -- + ≤64）→ 用之（用户拍板：frontmatter 覆盖 DB）
--   2) 否则现名合法 → 保留现名
--   3) 否则 → 'skill-<id>' 兜底（存量无 frontmatter/中文名的包）
--   同目标名冲突组：is_published 优先、次按 id 小者胜，败者追加 '-<id>' 后缀（仍 kebab 合法）。
-- 人工预检清单（待改名/非法兜底/冲突组）见 dev/migrate_090_preflight.py，
-- 部署前先跑 dry-run 过目；本 SQL 是其确定性等价实现，无需人工介入即可安全执行。

-- 1) 归一
WITH target AS (
    SELECT id, is_published,
           CASE
             WHEN frontmatter->>'name' ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'
                  AND position('--' in frontmatter->>'name') = 0
                  AND length(frontmatter->>'name') BETWEEN 1 AND 64
               THEN frontmatter->>'name'
             WHEN name ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'
                  AND position('--' in name) = 0
                  AND length(name) BETWEEN 1 AND 64
               THEN name
             ELSE 'skill-' || id
           END AS tgt
    FROM aihelms.skills
),
ranked AS (
    SELECT t.*, row_number() OVER (
        PARTITION BY tgt ORDER BY is_published DESC, id ASC) AS rn
    FROM target t
),
final AS (
    SELECT id, CASE WHEN rn = 1 THEN tgt ELSE tgt || '-' || id END AS final_name
    FROM ranked
)
UPDATE aihelms.skills s
SET name = f.final_name
FROM final f
WHERE s.id = f.id AND s.name <> f.final_name;

-- 2) 普通索引换唯一索引（冲突已被 1) 消解；重跑幂等）
DROP INDEX IF EXISTS aihelms.idx_skills_name;
CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_name ON aihelms.skills(name);

-- 3) 收敛计数（服务端日志 NOTICE，人工清单走预检脚本）
DO $$
DECLARE renamed_count INT; suffixed_count INT;
BEGIN
    SELECT count(*) INTO renamed_count FROM aihelms.skills
    WHERE name <> coalesce(frontmatter->>'name', name);
    SELECT count(*) INTO suffixed_count FROM aihelms.skills
    WHERE name ~ '-[0-9]+$' AND name <> regexp_replace(name, '-[0-9]+$', '');
    RAISE NOTICE '090 skill name unify: % rows diverge from frontmatter, % rows suffixed',
        renamed_count, suffixed_count;
END $$;
