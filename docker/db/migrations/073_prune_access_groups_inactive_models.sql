-- 073: 清理 model_access_groups.model_ids 中已物理删除的 model_id
-- 根因：delete_model 流程清 ai_keys.models（_remove_model_from_all_keys）但历史不清访问组，
-- 且早期未覆盖访问组。结果：模型删除后其 model_id 仍残留在访问组配置里，授权语义错乱。
-- 代码已修复（delete_model 新增 _remove_model_from_access_groups）。
-- 本迁移一次性回填存量：仅剔除 models 表已不存在的 model_id（物理删除），
-- 保留 inactive 模型（行还在，访问组配置语义不变，模型重新启用后引用仍有效）。幂等。

UPDATE aihelms.model_access_groups g
SET model_ids = COALESCE(
    (
        SELECT jsonb_agg(elem)
        FROM jsonb_array_elements_text(g.model_ids) AS elem
        WHERE EXISTS (
            SELECT 1 FROM aihelms.models m WHERE m.model_id = elem
        )
    ),
    '[]'::jsonb
),
    updated_at = NOW()
WHERE jsonb_typeof(g.model_ids) = 'array'
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(g.model_ids) AS elem
      WHERE NOT EXISTS (
          SELECT 1 FROM aihelms.models m WHERE m.model_id = elem
      )
  );
