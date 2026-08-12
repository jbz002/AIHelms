-- 074: 清理 ai_keys.skills/mcps/agents/mcp_budgets 中已删除资源的失效 id（覆盖所有 key_type，重点场景 Key）
-- 根因：remove_public_resource_from_all_keys 历史只遍历主 Key（find_all_main_keys 漏 *_scene），
-- 删除/下架 skill/mcp/agent 时场景 Key 的资源 id 不被清理，永久残留，授权与计数错乱。
-- 代码已修复（remove_public_resource_from_all_keys 改用 find_keys_referencing_* 覆盖所有 Key）。
-- 本迁移一次性回填存量：剔除源表已不存在的 id。幂等，可重复执行。

-- skills（数字数组）
UPDATE aihelms.ai_keys k
SET skills = COALESCE(
    (
        SELECT jsonb_agg(elem)
        FROM jsonb_array_elements(k.skills) AS elem
        WHERE EXISTS (
            SELECT 1 FROM aihelms.skills s WHERE s.id = (elem::text)::int
        )
    ),
    '[]'::jsonb
)
WHERE jsonb_typeof(k.skills) = 'array'
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(k.skills) AS elem
      WHERE NOT EXISTS (
          SELECT 1 FROM aihelms.skills s WHERE s.id = (elem::text)::int
      )
  );

-- mcps（数字数组）
UPDATE aihelms.ai_keys k
SET mcps = COALESCE(
    (
        SELECT jsonb_agg(elem)
        FROM jsonb_array_elements(k.mcps) AS elem
        WHERE EXISTS (
            SELECT 1 FROM aihelms.mcp_servers ms WHERE ms.id = (elem::text)::int
        )
    ),
    '[]'::jsonb
)
WHERE jsonb_typeof(k.mcps) = 'array'
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(k.mcps) AS elem
      WHERE NOT EXISTS (
          SELECT 1 FROM aihelms.mcp_servers ms WHERE ms.id = (elem::text)::int
      )
  );

-- mcp_budgets（dict，key 为 str(server_id)）
UPDATE aihelms.ai_keys k
SET mcp_budgets = COALESCE(
    (
        SELECT jsonb_object_agg(key, value)
        FROM jsonb_each(k.mcp_budgets)
        WHERE EXISTS (
            SELECT 1 FROM aihelms.mcp_servers ms WHERE ms.id = key::int
        )
    ),
    '{}'::jsonb
)
WHERE jsonb_typeof(k.mcp_budgets) = 'object'
  AND EXISTS (
      SELECT 1
      FROM jsonb_each(k.mcp_budgets)
      WHERE NOT EXISTS (
          SELECT 1 FROM aihelms.mcp_servers ms WHERE ms.id = key::int
      )
  );

-- agents（数字数组）
UPDATE aihelms.ai_keys k
SET agents = COALESCE(
    (
        SELECT jsonb_agg(elem)
        FROM jsonb_array_elements(k.agents) AS elem
        WHERE EXISTS (
            SELECT 1 FROM aihelms.agents a WHERE a.id = (elem::text)::int
        )
    ),
    '[]'::jsonb
)
WHERE jsonb_typeof(k.agents) = 'array'
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(k.agents) AS elem
      WHERE NOT EXISTS (
          SELECT 1 FROM aihelms.agents a WHERE a.id = (elem::text)::int
      )
  );
