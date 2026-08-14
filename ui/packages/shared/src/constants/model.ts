/** 能力位展示文案（英文 registry key → 中文）。已知能力给中文，未知（registry 新增 supports_*）由 capabilityLabel() 兜底 prettify。admin/web 共用。 */
export const CAPABILITY_LABELS: Record<string, string> = {
  vision: '视觉',
  reasoning: '推理',
  function_calling: '工具调用',
  response_schema: '结构化输出',
  native_structured_output: '原生结构化输出',
  parallel_function_calling: '并行工具调用',
  tool_choice: '工具选择',
  tool_search: '工具搜索',
  multilingual: '多语言',
  multimodal: '多模态',
  code: '代码',
  long_context: '长文本',
  image_gen: '文生图',
  image_input: '图像输入',
  tts: '语音合成',
  stt: '语音识别',
  video_gen: '文生视频',
  video_input: '视频输入',
  prompt_caching: '提示缓存',
  pdf_input: 'PDF输入',
  web_search: '联网搜索',
  url_context: 'URL上下文',
  system_messages: '系统消息',
  mid_conversation_system: '中途系统消息',
  audio_input: '音频输入',
  audio_output: '音频输出',
  computer_use: '计算机使用',
  assistant_prefill: '助手预填',
  native_streaming: '原生流式',
  speed: '速度优化',
  embedding_image_input: '向量图像输入',
  nova_canvas_image_edit: 'Nova 图像编辑',
}

/** 取能力中文文案；未知 key（registry 新增 supports_*）兜底 prettify：computer_use→Computer Use */
export function capabilityLabel(key: string): string {
  return CAPABILITY_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
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
