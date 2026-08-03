/**
 * 模型能力统一枚举。
 *
 * 取代旧的两套并行能力描述：
 * - 旧 `capabilities` JSONB 自由文本（中文：图像/推理/工具调用/多语言/多模态/代码/长文本）
 * - 旧 6 个 `supports_*` 布尔列（vision/function_calling/reasoning/response_schema/parallel_function_calling/tool_choice）
 *
 * 现统一为英文 snake_case 枚举值入库，中文展示文案由消费方（admin 直用 CAPABILITY_LABELS，web 走 i18n）映射。
 * 模态本身由 `category`（粗分类）+ `mode`（LiteLLM 精确 mode）承担，这里只描述跨模态的能力点。
 */
export type ModelCapability =
  | 'vision'
  | 'reasoning'
  | 'tools'
  | 'response_schema'
  | 'parallel_tool_calling'
  | 'tool_choice'
  | 'multilingual'
  | 'multimodal'
  | 'code'
  | 'long_context'
  | 'image_gen'
  | 'tts'
  | 'stt'
  | 'video_gen'
  | 'prompt_caching'
  | 'pdf_input'
  | 'web_search'
  | 'system_messages'
  | 'audio_input'
  | 'audio_output'

/** admin 端展示文案（admin 未 i18n）。web 端不使用此映射，走 i18n key。 */
export const CAPABILITY_LABELS: Record<ModelCapability, string> = {
  vision: '视觉',
  reasoning: '推理',
  tools: '工具调用',
  response_schema: '结构化输出',
  parallel_tool_calling: '并行工具',
  tool_choice: '工具选择',
  multilingual: '多语言',
  multimodal: '多模态',
  code: '代码',
  long_context: '长文本',
  image_gen: '文生图',
  tts: '语音合成',
  stt: '语音识别',
  video_gen: '文生视频',
  prompt_caching: '提示缓存',
  pdf_input: 'PDF输入',
  web_search: '联网搜索',
  system_messages: '系统消息',
  audio_input: '音频输入',
  audio_output: '音频输出',
}

/** 按 category 联动的能力候选（含模态标记，便于在对应分类下直接勾选）。 */
export const CATEGORY_CAPABILITIES: Record<string, ModelCapability[]> = {
  chat: [
    'vision',
    'reasoning',
    'tools',
    'response_schema',
    'parallel_tool_calling',
    'tool_choice',
    'multilingual',
    'multimodal',
    'code',
    'long_context',
    'prompt_caching',
    'pdf_input',
    'web_search',
    'system_messages',
    'audio_input',
    'audio_output',
  ],
  embedding: ['multilingual', 'multimodal', 'code', 'long_context'],
  rerank: ['multilingual', 'multimodal'],
  completion: ['reasoning', 'long_context'],
  image: ['image_gen', 'multilingual'],
  audio: ['tts', 'stt', 'multilingual'],
  video: ['video_gen', 'multilingual'],
}

/** 平台模型分类（模态粗分类）。audio 通过 mode 区分 TTS/STT，不再单列 tts。 */
export const MODEL_CATEGORIES = [
  { value: 'chat', label: '对话' },
  { value: 'embedding', label: '向量' },
  { value: 'rerank', label: '重排' },
  { value: 'completion', label: '补全' },
  { value: 'image', label: '文生图' },
  { value: 'audio', label: '语音' },
  { value: 'video', label: '文生视频' },
] as const

/** LiteLLM model_info.mode 取值集合（同步到 LiteLLM 用）。 */
export const LITELLM_MODES = [
  'chat',
  'embedding',
  'rerank',
  'completion',
  'image_generation',
  'audio_speech',
  'audio_transcription',
  'video_generation',
] as const

/** audio 分类下用户必须二选一的 mode。 */
export const AUDIO_MODES = ['audio_speech', 'audio_transcription'] as const
