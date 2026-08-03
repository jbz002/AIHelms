-- 063 模型多模态 mode 列 + capabilities 统一枚举重构
-- 1) 新增 mode 列（LiteLLM 精确 mode，同步用）
-- 2) capabilities 旧中文文本 → 英文 snake_case 枚举
-- 3) supports_* 6 布尔位 → 合并进 capabilities（不删旧列，向后兼容）
-- 4) mode 由 category 兜底回填
-- 5) 按 mode 补模态标记能力（image_gen/tts/stt/video_gen）
-- 6) 归一化旧 tts 分类 → audio
-- 7) provider_prefix_map 补多模态供应商前缀
-- 幂等、additive-only，可重跑。

-- 1) mode 列
ALTER TABLE aihelms.models ADD COLUMN IF NOT EXISTS mode VARCHAR(32);
COMMENT ON COLUMN aihelms.models.mode IS 'LiteLLM 精确 mode（同步用）：image_generation/audio_speech/audio_transcription/video_generation 等';

-- 2) capabilities 中文文本 → 英文枚举（删旧加新，WHERE 旧值存在保证幂等）
UPDATE aihelms.models SET capabilities = (capabilities - '图像')     || to_jsonb('vision'::text)     WHERE capabilities ? '图像';
UPDATE aihelms.models SET capabilities = (capabilities - '推理')     || to_jsonb('reasoning'::text)  WHERE capabilities ? '推理';
UPDATE aihelms.models SET capabilities = (capabilities - '工具调用') || to_jsonb('tools'::text)      WHERE capabilities ? '工具调用';
UPDATE aihelms.models SET capabilities = (capabilities - '多语言')   || to_jsonb('multilingual'::text) WHERE capabilities ? '多语言';
UPDATE aihelms.models SET capabilities = (capabilities - '多模态')   || to_jsonb('multimodal'::text) WHERE capabilities ? '多模态';
UPDATE aihelms.models SET capabilities = (capabilities - '代码')     || to_jsonb('code'::text)       WHERE capabilities ? '代码';
UPDATE aihelms.models SET capabilities = (capabilities - '长文本')   || to_jsonb('long_context'::text) WHERE capabilities ? '长文本';

-- 3) supports_* → capabilities 合并（NOT 已存在则加，不删旧列）
UPDATE aihelms.models SET capabilities = capabilities || to_jsonb('vision'::text)                WHERE supports_vision                   AND NOT capabilities ? 'vision';
UPDATE aihelms.models SET capabilities = capabilities || to_jsonb('reasoning'::text)             WHERE supports_reasoning                AND NOT capabilities ? 'reasoning';
UPDATE aihelms.models SET capabilities = capabilities || to_jsonb('tools'::text)                  WHERE supports_function_calling         AND NOT capabilities ? 'tools';
UPDATE aihelms.models SET capabilities = capabilities || to_jsonb('response_schema'::text)        WHERE supports_response_schema          AND NOT capabilities ? 'response_schema';
UPDATE aihelms.models SET capabilities = capabilities || to_jsonb('parallel_tool_calling'::text)  WHERE supports_parallel_function_calling AND NOT capabilities ? 'parallel_tool_calling';
UPDATE aihelms.models SET capabilities = capabilities || to_jsonb('tool_choice'::text)            WHERE supports_tool_choice              AND NOT capabilities ? 'tool_choice';

-- 6) 归一化旧 tts 分类 → audio（audio 通过 mode 区分 TTS/STT）
UPDATE aihelms.models SET category = 'audio' WHERE category = 'tts';

-- 4) mode 由 category 兜底回填（audio 历史多为 TTS，人工校正 STT）
UPDATE aihelms.models SET mode = 'image_generation'   WHERE category = 'image'      AND mode IS NULL;
UPDATE aihelms.models SET mode = 'audio_speech'       WHERE category = 'audio'      AND mode IS NULL;
UPDATE aihelms.models SET mode = 'video_generation'   WHERE category = 'video'      AND mode IS NULL;
UPDATE aihelms.models SET mode = 'chat'               WHERE category = 'chat'       AND mode IS NULL;
UPDATE aihelms.models SET mode = 'embedding'          WHERE category = 'embedding'  AND mode IS NULL;
UPDATE aihelms.models SET mode = 'rerank'             WHERE category = 'rerank'     AND mode IS NULL;
UPDATE aihelms.models SET mode = 'completion'         WHERE category = 'completion' AND mode IS NULL;

-- 5) 按 mode 补模态标记能力
UPDATE aihelms.models SET capabilities = capabilities || to_jsonb('image_gen'::text) WHERE mode = 'image_generation'    AND NOT capabilities ? 'image_gen';
UPDATE aihelms.models SET capabilities = capabilities || to_jsonb('tts'::text)       WHERE mode = 'audio_speech'        AND NOT capabilities ? 'tts';
UPDATE aihelms.models SET capabilities = capabilities || to_jsonb('stt'::text)       WHERE mode = 'audio_transcription' AND NOT capabilities ? 'stt';
UPDATE aihelms.models SET capabilities = capabilities || to_jsonb('video_gen'::text) WHERE mode = 'video_generation'    AND NOT capabilities ? 'video_gen';

-- 7) provider_prefix_map 多模态 seed
INSERT INTO aihelms.provider_prefix_map (provider_type, format, category, prefix, needs_v1) VALUES
    ('openai', 'openai', 'video', 'openai', false),
    ('azure', 'openai', 'image', 'azure', false),
    ('azure', 'openai', 'audio', 'azure', false),
    ('azure', 'openai', 'video', 'azure', false),
    ('google', 'openai', 'image', 'gemini', false),
    ('google', 'openai', 'audio', 'gemini', false),
    ('google', 'openai', 'video', 'gemini', false),
    ('bedrock', 'openai', 'image', 'bedrock', false),
    ('bedrock', 'openai', 'audio', 'bedrock', false),
    ('vertex_ai', 'openai', 'image', 'vertex_ai', false),
    ('vertex_ai', 'openai', 'audio', 'vertex_ai', false),
    ('vertex_ai', 'openai', 'video', 'vertex_ai', false),
    ('other', 'openai', 'image', 'openai', true),
    ('other', 'openai', 'audio', 'openai', true),
    ('other', 'openai', 'video', 'openai', true)
ON CONFLICT DO NOTHING;
