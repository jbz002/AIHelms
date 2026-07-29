-- 056: 去重 ai_keys 四类资源 JSONB 数组(models/mcps/skills/agents)中的重复元素
-- 根因:写入路径(create_ai_key / update_ai_key / update_key_resources)历史不去重,
-- sync_public_resource_to_all_keys(add)虽有 not in 保护但只覆盖主 Key,
-- 导致数组残留重复 id。前端「可用资源」计数 selected.length / pool.length
-- 出现 6/5,全选判定 selected.length === pool.length 失效(6===5 为 false),
-- 列表页资源数也偏大。代码已在 service 写入边界统一去重(见 _dedupe_preserve_order)。
-- 本迁移一次性回填存量脏数据:按首次出现顺序去重。幂等,可重复执行。

-- models(text 数组)
UPDATE aihelms.ai_keys
SET models = COALESCE(
    (
        SELECT jsonb_agg(elem ORDER BY ord)
        FROM (
            SELECT DISTINCT ON (elem) elem, ord
            FROM jsonb_array_elements_text(models) WITH ORDINALITY AS t(elem, ord)
            ORDER BY elem, ord
        ) s
    ),
    '[]'::jsonb
)
WHERE jsonb_typeof(models) = 'array'
  AND jsonb_array_length(models) >
      COALESCE(
          (SELECT count(DISTINCT elem) FROM jsonb_array_elements_text(models) AS t(elem)),
          0
      );

-- mcps(数字数组,jsonb_array_elements 保留 jsonb 数字类型,避免被 _text 转字符串)
UPDATE aihelms.ai_keys
SET mcps = COALESCE(
    (
        SELECT jsonb_agg(elem ORDER BY ord)
        FROM (
            SELECT DISTINCT ON (elem) elem, ord
            FROM jsonb_array_elements(mcps) WITH ORDINALITY AS t(elem, ord)
            ORDER BY elem, ord
        ) s
    ),
    '[]'::jsonb
)
WHERE jsonb_typeof(mcps) = 'array'
  AND jsonb_array_length(mcps) >
      COALESCE(
          (SELECT count(DISTINCT elem) FROM jsonb_array_elements(mcps) AS t(elem)),
          0
      );

-- skills(数字数组)
UPDATE aihelms.ai_keys
SET skills = COALESCE(
    (
        SELECT jsonb_agg(elem ORDER BY ord)
        FROM (
            SELECT DISTINCT ON (elem) elem, ord
            FROM jsonb_array_elements(skills) WITH ORDINALITY AS t(elem, ord)
            ORDER BY elem, ord
        ) s
    ),
    '[]'::jsonb
)
WHERE jsonb_typeof(skills) = 'array'
  AND jsonb_array_length(skills) >
      COALESCE(
          (SELECT count(DISTINCT elem) FROM jsonb_array_elements(skills) AS t(elem)),
          0
      );

-- agents(数字数组)
UPDATE aihelms.ai_keys
SET agents = COALESCE(
    (
        SELECT jsonb_agg(elem ORDER BY ord)
        FROM (
            SELECT DISTINCT ON (elem) elem, ord
            FROM jsonb_array_elements(agents) WITH ORDINALITY AS t(elem, ord)
            ORDER BY elem, ord
        ) s
    ),
    '[]'::jsonb
)
WHERE jsonb_typeof(agents) = 'array'
  AND jsonb_array_length(agents) >
      COALESCE(
          (SELECT count(DISTINCT elem) FROM jsonb_array_elements(agents) AS t(elem)),
          0
      );
