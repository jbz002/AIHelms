-- 035: 清理 ai_keys.models JSONB 中残留的 inactive / 已删除 model_id
-- 根因：_sync_published_model_to_main_keys 历史版本只看 is_published + requires_approval，
-- 不检查 is_active；且 update_model 改 is_active 时不触发 Key 同步。
-- 结果：禁用或删除的模型 id 残留在主 Key 的 models 数组里，而前端「可用 AI 资源」
-- 池只取 is_active=true 的模型，导致 selectedModels(=key.models) 比 pool 多，
-- 表现为「模型数量 6/5，多出来 1 个」。
-- 代码已修复（同步条件补 is_active、is_active 变更触发重新同步）。
-- 本迁移一次性回填现有脏数据：仅保留指向 active 模型的 model_id。幂等，可重复执行。

UPDATE aihelms.ai_keys k
SET models = COALESCE(
    (
        SELECT jsonb_agg(elem)
        FROM jsonb_array_elements_text(k.models) AS elem
        WHERE EXISTS (
            SELECT 1 FROM aihelms.models m
            WHERE m.model_id = elem AND m.is_active = true
        )
    ),
    '[]'::jsonb
)
WHERE jsonb_typeof(k.models) = 'array'
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(k.models) AS elem
      WHERE NOT EXISTS (
          SELECT 1 FROM aihelms.models m
          WHERE m.model_id = elem AND m.is_active = true
      )
  );
