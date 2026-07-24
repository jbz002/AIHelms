<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { testModelAccessStream, testEmbedding, testRerank } from '@aihelms/shared'
import { X, Eye, EyeOff, Zap } from 'lucide-vue-next'
import ProviderIcon from './ProviderIcon.vue'

interface ModelItem {
  id: number
  name: string
  model_id: string
  category: string
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

const openAiClients = ['Workbuddy', 'Qcoder', 'Openclaw', 'Dify', 'FastGPT', 'LobeChat', 'Cherry Studio']
const anthropicClients = ['Claude Code', 'Claude Desktop']

const copied = ref<string | null>(null)
const showKeyFull = ref(false)
const isTesting = ref(false)
const testOutput = ref('')
const testError = ref('')

const isChat = computed(() => props.model?.category === 'chat')
const showAnthropic = computed(() => !!props.model?.has_anthropic_deployment && isChat.value)
const maskedKey = computed(() => {
  const k = props.mainKeyValue
  return k ? (showKeyFull.value ? k : k.slice(0, 8) + '****' + k.slice(-4)) : t('modelSquare.fallback.noKey')
})

const openaiCurl = computed(() => {
  const m = props.model
  if (!m) return ''
  const u = props.litellmBaseUrl
  if (m.category === 'embedding') {
    return `curl ${u}/v1/embeddings \\\n  -H "Authorization: Bearer <your-api-key>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${m.model_id}", "input": "hello"}'`
  }
  if (m.category === 'rerank') {
    return `curl ${u}/v1/rerank \\\n  -H "Authorization: Bearer <your-api-key>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${m.model_id}", "query": "AI", "documents": ["人工智能是计算机科学的分支"]}'`
  }
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

async function handleTest(): Promise<void> {
  const m = props.model
  if (!m || isTesting.value) return
  isTesting.value = true
  testOutput.value = ''
  testError.value = ''
  try {
    if (m.category === 'embedding') {
      const res = await testEmbedding({ model: m.model_id, text: '你好世界' })
      if (res.success === false) testError.value = res.error || res.error_detail?.title || t('modelSquare.access.testPlaceholder')
      else testOutput.value = `✓ ${res.model || m.model_id} · ${t('modelSquare.access.testResult')} ${res.dimensions ?? ''}`
    } else if (m.category === 'rerank') {
      const res = await testRerank({ model: m.model_id, query: 'AI', documents: ['人工智能是计算机科学的分支', '今天天气很好'] })
      if (res.success === false) testError.value = res.error || res.error_detail?.title || t('modelSquare.access.testPlaceholder')
      else testOutput.value = `✓ ${res.model || m.model_id}\n${(res.results || []).map(r => `[${r.index}] ${r.relevance_score.toFixed(4)}`).join('\n')}`
    } else {
      await runChatStream(m.model_id)
    }
  } catch (e) {
    testError.value = e instanceof Error ? e.message : String(e)
  } finally {
    isTesting.value = false
  }
}

async function runChatStream(modelId: string): Promise<void> {
  const response = await testModelAccessStream({
    model: modelId,
    messages: [{ role: 'user', content: 'hi' }],
    stream: true,
    max_tokens: 100,
  })
  if (!response.ok) {
    testError.value = `HTTP ${response.status}`
    return
  }
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('text/event-stream')) {
    const json = await response.json()
    if (json.data?.success === false) {
      testError.value = json.data.error || json.data.error_detail?.title || t('modelSquare.access.testPlaceholder')
    } else {
      testOutput.value = json.data?.content || JSON.stringify(json.data || json)
    }
    return
  }
  const reader = response.body?.getReader()
  if (!reader) { testError.value = '无法读取响应流'; return }
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
        testError.value = data.slice(8).trim() || t('modelSquare.access.testPlaceholder')
        return
      }
      testOutput.value += data
    }
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
        <div class="rounded-lg border border-slate-200/60 p-4">
          <div class="mb-3 flex items-center gap-2">
            <span class="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">{{ t('modelSquare.access.openaiProtocol') }}</span>
            <span class="text-xs text-slate-400">{{ model.category }}</span>
          </div>
          <div class="mb-3 flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2.5">
            <div>
              <code class="text-sm font-medium text-slate-800">{{ model.model_id }}</code>
              <p v-if="isChat" class="mt-0.5 text-xs text-slate-400">
                {{ t('modelSquare.access.openaiClientsPrefix') }}
                <template v-for="(client, index) in openAiClients" :key="client">
                  <span v-if="index > 0">, </span><strong class="font-bold text-slate-500">{{ client }}</strong>
                </template>{{ t('modelSquare.access.openaiClientsSuffix') }}
              </p>
            </div>
            <button class="shrink-0 text-xs text-purple-600 hover:text-purple-700" @click="copyText(model.model_id, 'mid')">
              {{ copied === 'mid' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
            </button>
          </div>
          <p class="mb-1 text-xs font-medium text-slate-500">{{ t('modelSquare.access.curlLabel') }}</p>
          <div class="flex items-start justify-between gap-2 rounded-lg bg-slate-900 p-3">
            <pre class="flex-1 overflow-x-auto whitespace-pre-wrap break-all text-xs leading-5 text-slate-100">{{ openaiCurl }}</pre>
            <button class="shrink-0 text-xs text-purple-300 hover:text-purple-200" @click="copyText(openaiCurl, 'curl-openai')">
              {{ copied === 'curl-openai' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
            </button>
          </div>
          <p class="mt-1.5 text-xs text-slate-400">{{ t('modelSquare.access.curlHint') }}</p>
        </div>

        <div v-if="showAnthropic" class="rounded-lg border border-slate-200/60 p-4">
          <div class="mb-3">
            <span class="rounded-full bg-orange-50 px-2 py-0.5 text-xs font-semibold text-orange-700">{{ t('modelSquare.access.anthropicProtocol') }}</span>
          </div>
          <div class="mb-3 flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2.5">
            <div>
              <code class="text-sm font-medium text-slate-800">{{ model.model_id }}(Anthropic)</code>
              <p class="mt-0.5 text-xs text-slate-400">
                {{ t('modelSquare.access.anthropicClientsPrefix') }}
                <template v-for="(client, index) in anthropicClients" :key="client">
                  <span v-if="index > 0">, </span><strong class="font-bold text-slate-500">{{ client }}</strong>
                </template>{{ t('modelSquare.access.anthropicClientsSuffix') }}
              </p>
            </div>
            <button class="shrink-0 text-xs text-purple-600 hover:text-purple-700" @click="copyText(model.model_id + '(Anthropic)', 'mid-cc')">
              {{ copied === 'mid-cc' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
            </button>
          </div>
          <p class="mb-1 text-xs font-medium text-slate-500">{{ t('modelSquare.access.curlLabel') }}</p>
          <div class="flex items-start justify-between gap-2 rounded-lg bg-slate-900 p-3">
            <pre class="flex-1 overflow-x-auto whitespace-pre-wrap break-all text-xs leading-5 text-slate-100">{{ anthropicCurl }}</pre>
            <button class="shrink-0 text-xs text-purple-300 hover:text-purple-200" @click="copyText(anthropicCurl, 'curl-anthropic')">
              {{ copied === 'curl-anthropic' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
            </button>
          </div>
          <p class="mt-1.5 text-xs text-slate-400">{{ t('modelSquare.access.curlHint') }}</p>
        </div>

        <div class="rounded-lg bg-slate-50 p-4">
          <div class="mb-1 flex items-center justify-between">
            <span class="text-xs font-medium text-slate-500">API Key</span>
            <div class="flex items-center gap-2">
              <button v-if="mainKeyValue" class="flex items-center justify-center rounded p-0.5 text-slate-400 hover:text-slate-600" @click="showKeyFull = !showKeyFull">
                <EyeOff v-if="showKeyFull" class="h-3.5 w-3.5" /><Eye v-else class="h-3.5 w-3.5" />
              </button>
              <button class="text-xs text-purple-600 hover:text-purple-700" @click="copyText(mainKeyValue, 'key')">
                {{ copied === 'key' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
              </button>
            </div>
          </div>
          <code class="block break-all text-sm text-slate-800">{{ maskedKey }}</code>
        </div>

        <div class="rounded-lg bg-slate-50 p-4">
          <div class="mb-1 flex items-center justify-between">
            <span class="text-xs font-medium text-slate-500">Base URL</span>
            <button class="text-xs text-purple-600 hover:text-purple-700" @click="copyText(litellmBaseUrl, 'url')">
              {{ copied === 'url' ? t('modelSquare.action.copied') : t('modelSquare.action.copy') }}
            </button>
          </div>
          <code class="text-sm text-slate-800">{{ litellmBaseUrl || t('modelSquare.fallback.notConfigured') }}</code>
        </div>

        <div class="rounded-lg border border-slate-200/60 p-4">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-slate-500">{{ t('modelSquare.access.testResult') }}</span>
            <button :disabled="isTesting || !mainKeyValue" class="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-purple-600 to-blue-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-opacity disabled:opacity-50" @click="handleTest">
              <Zap class="h-3.5 w-3.5" />{{ isTesting ? t('modelSquare.access.testing') : t('modelSquare.access.testEndpoint') }}
            </button>
          </div>
          <div class="mt-2 min-h-[2.5rem] rounded-lg bg-slate-50 p-3 text-xs">
            <div v-if="testError" class="whitespace-pre-wrap break-all text-red-600">{{ testError }}</div>
            <div v-else-if="testOutput" class="whitespace-pre-wrap break-all text-slate-700">{{ testOutput }}</div>
            <div v-else class="text-slate-400">{{ t('modelSquare.access.testPlaceholder') }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
