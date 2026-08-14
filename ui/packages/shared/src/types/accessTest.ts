export type ChatContentBlock =
  | { type: 'text'; text: string }
  | { type: 'image_url'; image_url: { url: string } }

export interface ChatMessage {
  role: string
  content: string | ChatContentBlock[]
}

export interface TestAccessParams {
  model: string
  messages: ChatMessage[]
  stream?: boolean
  max_tokens?: number
  protocol?: 'openai' | 'anthropic'
}

export interface AccessTestErrorDetail {
  category: string
  title: string
  message: string
  technical_detail: string
  status_code?: number
}

export interface TestAccessResult {
  success: boolean
  content: string
  model?: string
  error?: string
  error_detail?: AccessTestErrorDetail
  usage?: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  }
}

export interface TestEmbeddingParams {
  model: string
  text?: string
}

export interface TestEmbeddingResult {
  success: boolean
  dimensions?: number
  model?: string
  error?: string
  error_detail?: AccessTestErrorDetail
  usage?: {
    prompt_tokens: number
    total_tokens: number
  }
}

export interface TestRerankParams {
  model: string
  query?: string
  documents?: string[]
}

export interface TestRerankResult {
  success: boolean
  results?: { index: number; relevance_score: number }[]
  model?: string
  error?: string
  error_detail?: AccessTestErrorDetail
}

export interface TestImageGenParams {
  model: string
  prompt?: string
}

export interface TestImageGenResult {
  success: boolean
  b64_json?: string
  model?: string
  error?: string
  error_detail?: AccessTestErrorDetail
}

export interface TestAudioSpeechParams {
  model: string
  text?: string
}

export interface TestAudioSpeechResult {
  success: boolean
  b64_audio?: string
  content_type?: string
  model?: string
  error?: string
  error_detail?: AccessTestErrorDetail
}

export interface TestAudioTranscriptionParams {
  model: string
  audio_base64: string
}

export interface TestAudioTranscriptionResult {
  success: boolean
  text?: string
  model?: string
  error?: string
  error_detail?: AccessTestErrorDetail
}
