<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { testModelAccessStream, testEmbedding, testRerank, testImageGeneration, testAudioSpeech, testAudioTranscription } from '@aihelms/shared'
import type { ChatContentBlock } from '@aihelms/shared'
import { X, Eye, EyeOff, Zap } from 'lucide-vue-next'
import ProviderIcon from './ProviderIcon.vue'

interface ModelItem {
  id: number
  name: string
  model_id: string
  category: string
  mode?: string | null
  capabilities: string[]
  description: string
  logo_provider_type: string
  is_published: boolean
  requires_approval: boolean
  deployment_count: number
  has_anthropic_deployment: boolean
}

const props = defineProps<{
  visible: boolean
  model: ModelItem | null
  mainKeyValue: string
  litellmBaseUrl: string
}>()

const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()

const MAX_IMAGE_BYTES = 4 * 1024 * 1024
const MAX_AUDIO_BYTES = 4 * 1024 * 1024

const copied = ref<string | null>(null)
const showKeyFull = ref(false)
const activeCurlTab = ref<'openai' | 'anthropic'>('openai')
const isTesting = ref(false)
const testOutput = ref('')
const testError = ref('')
const testImageSrc = ref('')
const testAudioSrc = ref('')
const abortController = ref<AbortController | null>(null)
let testEpoch = 0

// 附件:vision(图像理解)/ stt(语音识别)
const attachedImage = ref<string | null>(null)
const imageName = ref('')
const imageInput = ref<HTMLInputElement | null>(null)
const attachedAudio = ref<string | null>(null)
const audioName = ref('')
const audioInput = ref<HTMLInputElement | null>(null)

// 切换模型 / 关闭弹窗时,中断进行中的流并清空残留结果,避免 A 模型回复串到 B 模型
function resetTestState(): void {
  testEpoch++
  abortController.value?.abort()
  abortController.value = null
  isTesting.value = false
  testOutput.value = ''
  testError.value = ''
  testImageSrc.value = ''
  testAudioSrc.value = ''
}

function resetAttachments(): void {
  attachedImage.value = null
  imageName.value = ''
  if (imageInput.value) imageInput.value.value = ''
  attachedAudio.value = null
  audioName.value = ''
  if (audioInput.value) audioInput.value.value = ''
}

watch(() => props.visible, (v) => {
  if (!v) { resetTestState(); resetAttachments(); activeCurlTab.value = 'openai' }
})

watch(() => props.model, () => { resetTestState(); resetAttachments(); activeCurlTab.value = 'openai' })

// 统一 mode 解析:mode 优先,缺失时按 category 兜底(chat/embedding/rerank)
const resolvedMode = computed<string>(() => {
  const m = props.model
  if (m?.mode) return m.mode
  if (m?.category === 'embedding') return 'embedding'
  if (m?.category === 'rerank') return 'rerank'
  return 'chat'
})
const isChatMode = computed(() => {
  const mode = resolvedMode.value
  if (mode === 'chat' || mode === 'completion') return true
  return !props.model?.mode && props.model?.category === 'chat'
})
const isVideoMode = computed(() => resolvedMode.value === 'video_generation')
const supportsVision = computed(() => isChatMode.value && (props.model?.capabilities || []).includes('vision'))
const isAudioTranscription = computed(() => resolvedMode.value === 'audio_transcription')

const showAnthropic = computed(() => !!props.model?.has_anthropic_deployment && isChatMode.value)
const maskedKey = computed(() => {
  const k = props.mainKeyValue
  return k ? (showKeyFull.value ? k : k.slice(0, 8) + '****' + k.slice(-4)) : t('modelSquare.fallback.noKey')
})

const openaiCurl = computed(() => {
  const m = props.model
  if (!m) return ''
  const u = props.litellmBaseUrl
  const mode = resolvedMode.value
  if (mode === 'embedding')
    return `curl ${u}/v1/embeddings \\\n  -H "Authorization: Bearer <your-api-key>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${m.model_id}", "input": "hello"}'`
  if (mode === 'rerank')
    return `curl ${u}/v1/rerank \\\n  -H "Authorization: Bearer <your-api-key>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${m.model_id}", "query": "AI", "documents": ["人工智能是计算机科学的分支"]}'`
  if (mode === 'image_generation')
    return `curl ${u}/v1/images/generations \\\n  -H "Authorization: Bearer <your-api-key>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${m.model_id}", "prompt": "a cat on the moon", "n": 1, "size": "1024x1024"}'`
  if (mode === 'audio_speech')
    return `curl ${u}/v1/audio/speech \\\n  -H "Authorization: Bearer <your-api-key>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${m.model_id}", "input": "你好世界", "voice": "alloy"}' --output speech.mp3`
  if (mode === 'audio_transcription')
    return `curl ${u}/v1/audio/transcriptions \\\n  -H "Authorization: Bearer <your-api-key>" \\\n  -F "model=${m.model_id}" \\\n  -F "file=@audio.mp3"`
  if (mode === 'video_generation')
    return `# ${t('modelSquare.access.videoCurlPlaceholder')}\n# LiteLLM / OpenAI have no standard video-generation endpoint.\n# Call the provider SDK directly.`
  return `curl ${u}/v1/chat/completions \\\n  -H "Authorization: Bearer <your-api-key>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${m.model_id}", "messages": [{"role": "user", "content": "hi"}]}'`
})

const anthropicCurl = computed(() => {
  const m = props.model
  if (!m) return ''
  return `curl ${props.litellmBaseUrl}/v1/messages \\\n  -H "x-api-key: <your-api-key>" \\\n  -H "anthropic-version: 2023-06-01" \\\n  -H "content-type: application/json" \\\n  -d '{"model": "${m.model_id}(Anthropic)", "max_tokens": 100, "messages": [{"role": "user", "content": "hi"}]}'`
})

async function copyText(text: string, key: string): Promise<void> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    copied.value = key
    setTimeout(() => { copied.value = null }, 2000)
  } catch { /* ignore */ }
}

function handleImageChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (file.size > MAX_IMAGE_BYTES) {
    testError.value = t('modelSquare.access.imageTooLarge')
    input.value = ''
    return
  }
  testError.value = ''
  const reader = new FileReader()
  reader.onload = () => {
    attachedImage.value = reader.result as string
    imageName.value = file.name
  }
  reader.readAsDataURL(file)
}

function removeImage(): void {
  attachedImage.value = null
  imageName.value = ''
  if (imageInput.value) imageInput.value.value = ''
}

function handleAudioChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (file.size > MAX_AUDIO_BYTES) {
    testError.value = t('modelSquare.access.audioTooLarge')
    input.value = ''
    return
  }
  testError.value = ''
  const reader = new FileReader()
  reader.onload = () => {
    attachedAudio.value = reader.result as string
    audioName.value = file.name
  }
  reader.readAsDataURL(file)
}

function removeAudio(): void {
  attachedAudio.value = null
  audioName.value = ''
  if (audioInput.value) audioInput.value.value = ''
}

async function handleTest(): Promise<void> {
  const m = props.model
  if (!m || isTesting.value || isVideoMode.value) return
  resetTestState()
  const epoch = testEpoch
  isTesting.value = true
  try {
    const mode = resolvedMode.value
    if (mode === 'image_generation') {
      const res = await testImageGeneration({ model: m.model_id, prompt: '一只在月球上的猫' })
      if (epoch !== testEpoch) return
      if (res.success === false) testError.value = res.error || res.error_detail?.title || t('modelSquare.access.testPlaceholder')
      else if (res.b64_json) testImageSrc.value = `data:image/png;base64,${res.b64_json}`
    } else if (mode === 'audio_speech') {
      const res = await testAudioSpeech({ model: m.model_id, text: '你好世界' })
      if (epoch !== testEpoch) return
      if (res.success === false) testError.value = res.error || res.error_detail?.title || t('modelSquare.access.testPlaceholder')
      else if (res.b64_audio) testAudioSrc.value = `data:${res.content_type || 'audio/mpeg'};base64,${res.b64_audio}`
    } else if (mode === 'audio_transcription') {
      if (!attachedAudio.value) { testError.value = t('modelSquare.access.attachAudioFirst'); return }
      const res = await testAudioTranscription({ model: m.model_id, audio_base64: attachedAudio.value })
      if (epoch !== testEpoch) return
      if (res.success === false) testError.value = res.error || res.error_detail?.title || t('modelSquare.access.testPlaceholder')
      else testOutput.value = res.text || ''
    } else if (mode === 'embedding') {
      const res = await testEmbedding({ model: m.model_id, text: '你好世界' })
      if (epoch !== testEpoch) return
      if (res.success === false) testError.value = res.error || res.error_detail?.title || t('modelSquare.access.testPlaceholder')
      else testOutput.value = `✓ ${res.model || m.model_id} · ${t('modelSquare.access.testResult')} ${res.dimensions ?? ''}`
    } else if (mode === 'rerank') {
      const res = await testRerank({ model: m.model_id, query: 'AI', documents: ['人工智能是计算机科学的分支', '今天天气很好'] })
      if (epoch !== testEpoch) return
      if (res.success === false) testError.value = res.error || res.error_detail?.title || t('modelSquare.access.testPlaceholder')
      else testOutput.value = `✓ ${res.model || m.model_id}\n${(res.results || []).map(r => `[${r.index}] ${r.relevance_score.toFixed(4)}`).join('\n')}`
    } else {
      await runChatStream(m.model_id, epoch)
    }
  } catch (e) {
    if (epoch !== testEpoch) return
    if (e instanceof DOMException && e.name === 'AbortError') return
    testError.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (epoch === testEpoch) isTesting.value = false
  }
}

async function runChatStream(modelId: string, epoch: number): Promise<void> {
  const controller = new AbortController()
  abortController.value = controller
  try {
    // vision:附加图片时构造多模态 content,否则纯文本
    let content: string | ChatContentBlock[]
    if (attachedImage.value) {
      content = [
        { type: 'text', text: '请描述这张图片' },
        { type: 'image_url', image_url: { url: attachedImage.value } },
      ]
    } else {
      content = 'hi'
    }
    const response = await testModelAccessStream({
      model: modelId,
      messages: [{ role: 'user', content }],
      stream: true,
      max_tokens: 100,
    }, controller.signal)
    if (!response.ok) {
      if (epoch === testEpoch) testError.value = `HTTP ${response.status}`
      return
    }
    const contentType = response.headers.get('content-type') || ''
    if (!contentType.includes('text/event-stream')) {
      const json = await response.json()
      if (epoch !== testEpoch) return
      if (json.data?.success === false) {
        testError.value = json.data.error || json.data.error_detail?.title || t('modelSquare.access.testPlaceholder')
      } else {
        testOutput.value = json.data?.content || JSON.stringify(json.data || json)
      }
      return
    }
    const reader = response.body?.getReader()
    if (!reader) { if (epoch === testEpoch) testError.value = '无法读取响应流'; return }
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const data = line.slice(6)
        if (data === '[DONE]') return
        if (data.startsWith('[ERROR]')) {
          if (epoch === testEpoch) testError.value = data.slice(8).trim() || t('modelSquare.access.testPlaceholder')
          return
        }
        if (epoch === testEpoch) testOutput.value += data
      }
    }
  } catch (e) {
    if (controller.signal.aborted || (e instanceof DOMException && e.name === 'AbortError')) return
    throw e
  } finally {
    if (abortController.value === controller) abortController.value = null
  }
}
</script>

<template>
  <div v-if="visible && model" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30" @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border border-slate-200/60 bg-white shadow-2xl">
      <div class="flex items-center justify-between border-b border-slate-100 px-6 py-4">
        <div class="flex items-center gap-3">
          <ProviderIcon v-if="model.logo_provider_type" :type="model.logo_provider_type" :size="24" />
          <h3 class="text-base font-semibold text-slate-900">{{ model.name }}</h3>
        </div>
        <button class="rounded-lg p-1 hover:bg-slate-100" @click="emit('close')"><X class="h-4 w-4 text-slate-400" /></button>
      </div>

      <div class="flex-1 space-y-4 overflow-y-auto px-6 py-5">
        <!-- 顶部:模型名称 / Base URL / API Key -->
        <div class="space-y-2 rounded-lg border border-slate-200/60 p-4">
          <div class="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2">
            <div class="flex min-w-0 items-baseline gap-2">
              <span class="shrink-0 text-xs text-slate-400">{{ t('modelSquare.access.modelId') }}</span>
              <code class="truncate text-sm font-medium text-slate-800">{{ model.model_id }}</code>
            </div>
            <button class="shrink-0 text-xs text-purple-600 hover:text-purple-700" @click="copyText(model.model_id, 'mid')">
              {{ copied === 'mid' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
            </button>
          </div>

          <div class="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2">
            <div class="flex min-w-0 items-baseline gap-2">
              <span class="shrink-0 text-xs text-slate-400">Base URL</span>
              <code class="truncate text-sm text-slate-800">{{ litellmBaseUrl || t('modelSquare.fallback.notConfigured') }}</code>
            </div>
            <button class="shrink-0 text-xs text-purple-600 hover:text-purple-700" @click="copyText(litellmBaseUrl, 'url')">
              {{ copied === 'url' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
            </button>
          </div>

          <div class="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2">
            <div class="flex min-w-0 flex-1 items-baseline gap-2">
              <span class="shrink-0 text-xs text-slate-400">API Key</span>
              <code class="break-all text-sm text-slate-800">{{ maskedKey }}</code>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <button v-if="mainKeyValue" class="rounded p-0.5 text-slate-400 hover:text-slate-600" @click="showKeyFull = !showKeyFull">
                <EyeOff v-if="showKeyFull" class="h-3.5 w-3.5" /><Eye v-else class="h-3.5 w-3.5" />
              </button>
              <button class="text-xs text-purple-600 hover:text-purple-700" @click="copyText(mainKeyValue, 'key')">
                {{ copied === 'key' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
              </button>
            </div>
          </div>
        </div>

        <!-- curl 示例(OpenAI / Anthropic tab 切换) -->
        <div class="rounded-lg border border-slate-200/60 p-4">
          <div v-if="showAnthropic" class="mb-3 flex gap-1 rounded-lg bg-slate-100 p-1">
            <button class="flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
              :class="activeCurlTab === 'openai' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
              @click="activeCurlTab = 'openai'">{{ t('modelSquare.access.openaiProtocol') }}</button>
            <button class="flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
              :class="activeCurlTab === 'anthropic' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
              @click="activeCurlTab = 'anthropic'">{{ t('modelSquare.access.anthropicProtocol') }}</button>
          </div>
          <p class="mb-1 text-xs font-medium text-slate-500">{{ t('modelSquare.access.curlLabel') }}</p>
          <div v-show="activeCurlTab === 'openai'" class="flex items-start justify-between gap-2 rounded-lg bg-slate-900 p-3">
            <pre class="flex-1 overflow-x-auto whitespace-pre-wrap break-all text-xs leading-5 text-slate-100">{{ openaiCurl }}</pre>
            <button class="shrink-0 text-xs text-purple-300 hover:text-purple-200" @click="copyText(openaiCurl, 'curl-openai')">
              {{ copied === 'curl-openai' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
            </button>
          </div>
          <div v-if="showAnthropic" v-show="activeCurlTab === 'anthropic'" class="flex items-start justify-between gap-2 rounded-lg bg-slate-900 p-3">
            <pre class="flex-1 overflow-x-auto whitespace-pre-wrap break-all text-xs leading-5 text-slate-100">{{ anthropicCurl }}</pre>
            <button class="shrink-0 text-xs text-purple-300 hover:text-purple-200" @click="copyText(anthropicCurl, 'curl-anthropic')">
              {{ copied === 'curl-anthropic' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
            </button>
          </div>
          <p class="mt-1.5 text-xs text-slate-400">{{ t('modelSquare.access.curlHint') }}</p>
        </div>

        <div class="rounded-lg border border-slate-200/60 p-4">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-slate-500">{{ t('modelSquare.access.testResult') }}</span>
            <button :disabled="isTesting || !mainKeyValue || isVideoMode" class="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-purple-600 to-blue-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-opacity disabled:opacity-50" @click="handleTest">
              <Zap class="h-3.5 w-3.5" />{{ isTesting ? t('modelSquare.access.testing') : t('modelSquare.access.testEndpoint') }}
            </button>
          </div>

          <div v-if="supportsVision" class="mt-2">
            <input ref="imageInput" type="file" accept="image/*" class="hidden" @change="handleImageChange" />
            <div v-if="attachedImage" class="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2">
              <img :src="attachedImage" alt="" class="h-12 w-12 rounded object-cover" />
              <span class="flex-1 truncate text-xs text-slate-600">{{ imageName }}</span>
              <button class="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-600" @click="removeImage"><X class="h-3.5 w-3.5" /></button>
            </div>
            <button v-else class="rounded-lg border border-dashed border-slate-300 px-3 py-1.5 text-xs text-slate-500 transition-colors hover:border-purple-400 hover:text-purple-500" @click="imageInput?.click()">
              {{ t('modelSquare.access.attachImage') }}
            </button>
          </div>

          <div v-if="isAudioTranscription" class="mt-2">
            <input ref="audioInput" type="file" accept="audio/*" class="hidden" @change="handleAudioChange" />
            <div v-if="attachedAudio" class="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2">
              <span class="flex-1 truncate text-xs text-slate-600">{{ audioName }}</span>
              <button class="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-600" @click="removeAudio"><X class="h-3.5 w-3.5" /></button>
            </div>
            <button v-else class="rounded-lg border border-dashed border-slate-300 px-3 py-1.5 text-xs text-slate-500 transition-colors hover:border-purple-400 hover:text-purple-500" @click="audioInput?.click()">
              {{ t('modelSquare.access.attachAudio') }}
            </button>
          </div>

          <p v-if="isVideoMode" class="mt-2 text-xs text-slate-400">{{ t('modelSquare.access.videoTestDisabledHint') }}</p>

          <div class="mt-2 min-h-[2.5rem] rounded-lg bg-slate-50 p-3 text-xs">
            <div v-if="testError" class="whitespace-pre-wrap break-all text-red-600">{{ testError }}</div>
            <img v-else-if="testImageSrc" :src="testImageSrc" alt="" class="max-h-48 rounded" />
            <audio v-else-if="testAudioSrc" :src="testAudioSrc" controls class="w-full" />
            <div v-else-if="testOutput" class="whitespace-pre-wrap break-all text-slate-700">{{ testOutput }}</div>
            <div v-else class="text-slate-400">{{ t('modelSquare.access.testPlaceholder') }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
