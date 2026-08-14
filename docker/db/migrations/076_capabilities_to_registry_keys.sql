-- 076: capabilities 统一到 registry 原始 key（supports_* 去前缀）
--
-- 背景：历史 capabilities 存平台自定义枚举（tools / parallel_tool_calling …），
-- 与 registry-meta 喂前端的 registry 原生 key（function_calling / parallel_function_calling …）
-- 命名分歧。本次统一为 registry 原生 key，并移除 registry 无 supports_ 位的平台能力
-- （模态 image_gen/tts/stt/video_gen 归 category/mode；跨模态 multilingual/multimodal/code/long_context）。
--
-- 幂等：重跑无变化（目标 key 已替换、移除 key 已不存在）。改值不改结构。

UPDATE aihelms.models
SET capabilities = COALESCE(
  (
    SELECT jsonb_agg(
      CASE
        WHEN elem #>> '{}' = 'tools' THEN to_jsonb('function_calling'::text)
        WHEN elem #>> '{}' = 'parallel_tool_calling' THEN to_jsonb('parallel_function_calling'::text)
        ELSE elem
      END
    )
    FROM jsonb_array_elements(capabilities) AS elem
    WHERE elem #>> '{}' NOT IN (
      'image_gen', 'tts', 'stt', 'video_gen',
      'multilingual', 'multimodal', 'code', 'long_context'
    )
  ),
  '[]'::jsonb
)
WHERE capabilities IS NOT NULL AND jsonb_array_length(capabilities) > 0;
