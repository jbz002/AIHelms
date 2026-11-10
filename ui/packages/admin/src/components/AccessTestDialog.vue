<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { cacheProbe, historyProbe, resyncAnthropicDeployments, testModelAccessStream, thinkingProbe, toast, toolProbe, usePermission } from '@aihelms/shared'
import type { AccessTestErrorDetail, CacheProbeResult, ChatContentBlock, HistoryProbeResult, ThinkingProbeResult, ToolProbeResult } from '@aihelms/shared'

interface Props {
  visible: boolean
  defaultModel?: string
  defaultCredentialName?: string
  availableModels?: string[]
  supportsVision?: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
  close: []
}>()
const { hasPermission } = usePermission()

const modelInput = ref('')
const messageInput = ref('你好，请简单介绍一下你自己。')
const maxTokens = ref(100)
const streamEnabled = ref(true)
const outputContent = ref('')
const isStreaming = ref(false)
const errorMsg = ref('')
const errorDetail = ref<AccessTestErrorDetail | null>(null)
const showTechnicalDetail = ref(false)
const isResyncingAnthropic = ref(false)

const attachedImage = ref<string | null>(null)
const imageName = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const MAX_IMAGE_BYTES = 4 * 1024 * 1024

const probeRunning = ref(false)
const probeResult = ref<ToolProbeResult | null>(null)
const probeErrorMsg = ref('')
const thinkingProbeRunning = ref(false)
const thinkingProbeResult = ref<ThinkingProbeResult | null>(null)
const thinkingProbeErrorMsg = ref('')
const historyProbeRunning = ref(false)
const historyProbeResult = ref<HistoryProbeResult | null>(null)
const historyProbeErrorMsg = ref('')
const replayModelInput = ref('')
const cacheProbeRunning = ref(false)
const cacheProbeResult = ref<CacheProbeResult | null>(null)
const cacheProbeErrorMsg = ref('')

// 一键检测：五个检查项依次执行，状态条展示（对齐部署健康检测的观感）
type CheckKey = 'send' | 'tool' | 'thinking' | 'history' | 'cache'
type CheckState = 'pending' | 'running' | 'pass' | 'fail' | 'skipped'
type ProbeOutcome = { success: boolean; error_detail?: AccessTestErrorDetail } | null

const CHECK_ITEMS: { key: CheckKey; label: string }[] = [
  { key: 'send', label: '发送测试' },
  { key: 'tool', label: '工具调用' },
  { key: 'thinking', label: 'Thinking' },
  { key: 'history', label: '历史回放' },
  { key: 'cache', label: 'Prompt Cache' },
]

function initialCheckStates(): Record<CheckKey, CheckState> {
  return { send: 'pending', tool: 'pending', thinking: 'pending', history: 'pending', cache: 'pending' }
}

const checkStates = ref<Record<CheckKey, CheckState>>(initialCheckStates())
const checkStarted = computed(() => Object.values(checkStates.value).some((s) => s !== 'pending'))
const fullCheckRunning = computed(() => Object.values(checkStates.value).some((s) => s === 'running'))

watch(() => props.visible, (val) => {
  if (val) {
    modelInput.value = props.defaultModel || ''
    outputContent.value = ''
    errorMsg.value = ''
    errorDetail.value = null
    showTechnicalDetail.value = false
    isStreaming.value = false
    isResyncingAnthropic.value = false
    attachedImage.value = null
    imageName.value = ''
    probeRunning.value = false
    probeResult.value = null
    probeErrorMsg.value = ''
    thinkingProbeRunning.value = false
    thinkingProbeResult.value = null
    thinkingProbeErrorMsg.value = ''
    historyProbeRunning.value = false
    historyProbeResult.value = null
    historyProbeErrorMsg.value = ''
    replayModelInput.value = ''
    cacheProbeRunning.value = false
    cacheProbeResult.value = null
    cacheProbeErrorMsg.value = ''
    checkStates.value = initialCheckStates()
    if (fileInput.value) fileInput.value.value = ''
  }
})

const canSend = computed(() => {
  const hasMessage = messageInput.value.trim().length > 0
  const hasImage = attachedImage.value !== null
  return modelInput.value.trim() && (hasMessage || hasImage) && !isStreaming.value
})

const canResyncAnthropicAccess = computed(() => {
  return errorDetail.value?.category === 'upstream_permission_denied' && hasPermission('user:update')
})

async function handleSend(): Promise<void> {
  if (!canSend.value) return

  outputContent.value = ''
  errorMsg.value = ''
  errorDetail.value = null
  showTechnicalDetail.value = false
  isStreaming.value = true

  try {
    const text = messageInput.value.trim()
    let content: string | ChatContentBlock[]
    if (attachedImage.value) {
      content = [
        { type: 'text', text: text || '请描述这张图片' },
        { type: 'image_url', image_url: { url: attachedImage.value } },
      ]
    } else {
      content = text
    }
    const response = await testModelAccessStream({
      model: modelInput.value.trim(),
      messages: [{ role: 'user', content }],
      stream: streamEnabled.value,
      max_tokens: maxTokens.value,
    })

    if (!response.ok) {
      const text = await response.text()
      errorMsg.value = `请求失败: ${response.status} - ${text}`
      isStreaming.value = false
      return
    }

    // 非流式响应（embedding/rerank 返回 JSON）
    const contentType = response.headers.get('content-type') || ''
    if (!contentType.includes('text/event-stream')) {
      const json = await response.json()
      if (json.data?.success === false) {
        setAccessError(json.data.error_detail, json.data.error || '测试失败')
      } else if (json.data?.dimensions !== undefined) {
        outputContent.value = `测试成功\n维度: ${json.data.dimensions}\n模型: ${json.data.model}\nTokens: ${json.data.usage?.prompt_tokens || 0}`
      } else if (json.data?.results) {
        const lines = json.data.results.map((r: { index: number; relevance_score: number }) =>
          `[${r.index}] 相关度: ${r.relevance_score.toFixed(4)}`)
        outputContent.value = `测试成功\n模型: ${json.data.model}\n排序结果:\n${lines.join('\n')}`
      } else {
        outputContent.value = json.data?.content || JSON.stringify(json.data)
      }
      isStreaming.value = false
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      errorMsg.value = '无法读取响应流'
      isStreaming.value = false
      return
    }

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
        if (data === '[DONE]') {
          isStreaming.value = false
          return
        }
        if (data.startsWith('[ERROR]')) {
          setAccessErrorFromStream(data.slice(8).trim())
          isStreaming.value = false
          return
        }
        outputContent.value += data
      }
    }
  } catch (e) {
    errorMsg.value = `连接错误: ${e instanceof Error ? e.message : String(e)}`
  } finally {
    isStreaming.value = false
  }
}

function handleClose(): void {
  emit('close')
}

async function handleToolProbe(): Promise<void> {
  const model = modelInput.value.trim()
  if (!model || probeRunning.value) return
  probeRunning.value = true
  probeResult.value = null
  probeErrorMsg.value = ''
  try {
    probeResult.value = await toolProbe({ model })
  } catch (e) {
    probeErrorMsg.value = e instanceof Error ? e.message : '探针请求失败'
  } finally {
    probeRunning.value = false
  }
}

function verdictModeLabel(mode: string): string {
  return mode === 'stream' ? '流式' : '非流式'
}

async function handleThinkingProbe(): Promise<void> {
  const model = modelInput.value.trim()
  if (!model || thinkingProbeRunning.value) return
  thinkingProbeRunning.value = true
  thinkingProbeResult.value = null
  thinkingProbeErrorMsg.value = ''
  try {
    thinkingProbeResult.value = await thinkingProbe({ model })
  } catch (e) {
    thinkingProbeErrorMsg.value = e instanceof Error ? e.message : '探针请求失败'
  } finally {
    thinkingProbeRunning.value = false
  }
}

async function handleHistoryProbe(): Promise<void> {
  const model = modelInput.value.trim()
  if (!model || historyProbeRunning.value) return
  historyProbeRunning.value = true
  historyProbeResult.value = null
  historyProbeErrorMsg.value = ''
  try {
    historyProbeResult.value = await historyProbe({
      model,
      replay_model: replayModelInput.value.trim() || undefined,
    })
  } catch (e) {
    historyProbeErrorMsg.value = e instanceof Error ? e.message : '探针请求失败'
  } finally {
    historyProbeRunning.value = false
  }
}

async function handleCacheProbe(): Promise<void> {
  const model = modelInput.value.trim()
  if (!model || cacheProbeRunning.value) return
  cacheProbeRunning.value = true
  cacheProbeResult.value = null
  cacheProbeErrorMsg.value = ''
  try {
    cacheProbeResult.value = await cacheProbe({ model })
  } catch (e) {
    cacheProbeErrorMsg.value = e instanceof Error ? e.message : '探针请求失败'
  } finally {
    cacheProbeRunning.value = false
  }
}

function probePassed(result: ProbeOutcome, errMsg: string): boolean {
  return !errMsg && !!result && !result.error_detail && result.success
}

async function runCheckStep(key: CheckKey, action: () => Promise<void>, passed: () => boolean): Promise<void> {
  checkStates.value[key] = 'running'
  await action()
  checkStates.value[key] = passed() ? 'pass' : 'fail'
}

async function handleRunAllChecks(): Promise<void> {
  if (!modelInput.value.trim() || fullCheckRunning.value) return
  checkStates.value = initialCheckStates()

  checkStates.value.send = 'running'
  await handleSend()
  const sendOk = !errorMsg.value && outputContent.value !== ''
  checkStates.value.send = sendOk ? 'pass' : 'fail'
  // 基础连通失败（无权限/未发布/上游不可达）时探针只会重复同样的错误，直接跳过
  if (!sendOk) {
    for (const item of CHECK_ITEMS) {
      if (checkStates.value[item.key] === 'pending') checkStates.value[item.key] = 'skipped'
    }
    return
  }

  await runCheckStep('tool', handleToolProbe, () => probePassed(probeResult.value, probeErrorMsg.value))
  await runCheckStep('thinking', handleThinkingProbe, () => probePassed(thinkingProbeResult.value, thinkingProbeErrorMsg.value))
  await runCheckStep('history', handleHistoryProbe, () => probePassed(historyProbeResult.value, historyProbeErrorMsg.value))
  await runCheckStep('cache', handleCacheProbe, () => probePassed(cacheProbeResult.value, cacheProbeErrorMsg.value))
}

function checkChipClass(state: CheckState): string {
  if (state === 'pass') return 'bg-emerald-50 text-emerald-600'
  if (state === 'fail') return 'bg-red-50 text-red-600'
  if (state === 'running') return 'bg-blue-50 text-blue-600'
  return 'bg-slate-100 text-slate-400'
}

function checkMark(state: CheckState): string {
  if (state === 'pass') return '✓'
  if (state === 'fail') return '✗'
  if (state === 'skipped') return '–'
  return '·'
}

function checkStateLabel(state: CheckState): string {
  if (state === 'running') return '检测中'
  if (state === 'skipped') return '已跳过'
  if (state === 'pending') return '未执行'
  if (state === 'pass') return '通过'
  return '未通过'
}

function handleFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (file.size > MAX_IMAGE_BYTES) {
    toast.error('图片过大，请选择小于 4MB 的图片')
    input.value = ''
    return
  }
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
  if (fileInput.value) fileInput.value.value = ''
}

async function handleResyncAnthropicAccess(): Promise<void> {
  if (isResyncingAnthropic.value) return
  isResyncingAnthropic.value = true
  try {
    const result = await resyncAnthropicDeployments()
    toast.success(`同步完成，请重新测试（更新 Key：${result.keys_updated}）`)
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '同步失败')
  } finally {
    isResyncingAnthropic.value = false
  }
}

function setAccessError(detail: AccessTestErrorDetail | undefined, fallback: string): void {
  if (detail) {
    errorDetail.value = detail
    errorMsg.value = detail.title || fallback
    return
  }
  errorMsg.value = fallback
}

function setAccessErrorFromStream(payload: string): void {
  try {
    const parsed = JSON.parse(payload) as AccessTestErrorDetail
    setAccessError(parsed, parsed.title || '测试失败')
  } catch {
    errorMsg.value = payload || '测试失败'
  }
}
</script>

<template>
  <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
    <div class="flex w-full max-w-2xl flex-col rounded-2xl border border-slate-200/60 bg-white shadow-xl" style="max-height: 80vh;">
      <!-- Header -->
      <div class="flex items-center justify-between border-b border-slate-100 px-6 py-4">
        <h3 class="text-lg font-semibold text-slate-900">访问测试</h3>
        <button
          class="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          @click="handleClose"
        >
          <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Body -->
      <div class="flex-1 overflow-y-auto px-6 py-4">
        <!-- Model select -->
        <div class="mb-4">
          <label class="mb-1.5 block text-sm font-medium text-slate-700">模型</label>
          <div class="flex gap-2">
            <input
              v-model="modelInput"
              type="text"
              placeholder="输入模型 ID（如 claude-opus-4-6）"
              class="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition-colors focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
            />
            <select
              v-if="availableModels && availableModels.length > 0"
              v-model="modelInput"
              class="w-48 shrink-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition-colors focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
            >
              <option value="" disabled>选择可用模型</option>
              <option v-for="m in availableModels" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
        </div>

        <!-- Message input -->
        <div class="mb-4">
          <label class="mb-1.5 block text-sm font-medium text-slate-700">测试消息</label>
          <textarea
            v-model="messageInput"
            rows="3"
            :placeholder="attachedImage ? '可选，留空则默认「请描述这张图片」' : '输入测试消息...'"
            class="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition-colors focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          />
        </div>

        <!-- Image attachment (vision test) -->
        <div v-if="supportsVision" class="mb-4">
          <input
            ref="fileInput"
            type="file"
            accept="image/*"
            class="hidden"
            @change="handleFileChange"
          />
          <div v-if="attachedImage" class="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-2">
            <img :src="attachedImage" alt="附件" class="h-16 w-16 rounded-md object-cover" />
            <span class="flex-1 truncate text-xs text-slate-600">{{ imageName }}</span>
            <button
              type="button"
              class="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-600"
              @click="removeImage"
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <button
            v-else
            type="button"
            class="rounded-lg border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-500 transition-colors hover:border-blue-400 hover:text-blue-500"
            @click="fileInput?.click()"
          >
            + 附加图片（测试图像理解，≤4MB）
          </button>
        </div>

        <!-- Parameters -->
        <div class="mb-4 flex items-center gap-4">
          <div class="flex items-center gap-2">
            <label class="text-xs text-slate-500">Max Tokens</label>
            <input
              v-model.number="maxTokens"
              type="number"
              min="1"
              max="4096"
              class="w-20 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-900 outline-none focus:border-blue-400"
            />
          </div>
          <label class="flex items-center gap-1.5 text-xs text-slate-500">
            <input
              v-model="streamEnabled"
              type="checkbox"
              class="h-3.5 w-3.5 rounded border-slate-300 text-blue-500 focus:ring-blue-400/20"
            />
            流式响应
          </label>
        </div>

        <!-- 连通测试（轻量）与全量健康检查（五项串行）两个入口 -->
        <div class="mb-4 flex items-center gap-3">
          <button
            :disabled="!canSend"
            class="rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
            @click="handleSend"
          >
            <span v-if="isStreaming" class="flex items-center gap-2">
              <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              测试中...
            </span>
            <span v-else>发送测试</span>
          </button>
          <button
            :disabled="!modelInput.trim() || fullCheckRunning"
            class="rounded-lg border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-600 transition-colors hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
            @click="handleRunAllChecks"
          >
            <span v-if="fullCheckRunning" class="flex items-center gap-2">
              <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              检测中...
            </span>
            <span v-else>全量健康检查</span>
          </button>
          <span class="text-xs text-slate-400">全量检查依次执行五项；Prompt Cache 探针约 2×3.6k tokens 计费</span>
        </div>

        <!-- 检测状态条 -->
        <div v-if="checkStarted" class="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div class="flex flex-wrap items-center gap-2">
            <span
              v-for="item in CHECK_ITEMS"
              :key="item.key"
              class="flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
              :class="checkChipClass(checkStates[item.key])"
            >
              <svg v-if="checkStates[item.key] === 'running'" class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span v-else>{{ checkMark(checkStates[item.key]) }}</span>
              {{ item.label }}·{{ checkStateLabel(checkStates[item.key]) }}
            </span>
          </div>
          <p v-if="checkStates.send === 'fail'" class="mt-2 text-xs leading-5 text-amber-700">
            发送测试未通过，其余检测已跳过——请先解决基础连通问题（见下方错误详情）。
          </p>
        </div>

        <div class="mb-4">
          <input
            v-model="replayModelInput"
            placeholder="历史回放目标模型（可选；切换模型场景填另一方言组，留空=当前模型）"
            class="flex h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500/50 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>

        <!-- Tool probe result -->
        <div v-if="probeResult || probeErrorMsg" class="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <label class="mb-2 block text-xs font-medium text-slate-500">工具调用探针（{{ probeResult?.protocol === 'anthropic' ? 'Anthropic' : 'OpenAI' }} 协议）</label>
          <div v-if="probeErrorMsg" class="text-sm text-red-600">{{ probeErrorMsg }}</div>
          <template v-else-if="probeResult">
            <div v-if="probeResult.error_detail" class="text-sm text-red-600">{{ probeResult.error_detail.title || '探针无法执行' }}</div>
            <ul v-else class="space-y-1">
              <li v-for="v in probeResult.verdicts" :key="v.mode" class="flex items-start gap-2 text-sm">
                <span :class="v.ok ? 'text-green-600' : 'text-red-600'">{{ v.ok ? '✓' : '✗' }}</span>
                <span class="font-medium text-slate-700">{{ verdictModeLabel(v.mode) }}：</span>
                <span :class="v.ok ? 'text-slate-600' : 'text-red-600'">{{ v.detail }}</span>
              </li>
            </ul>
            <p v-if="!probeResult.success && !probeResult.error_detail" class="mt-2 text-xs leading-5 text-amber-700">
              工具调用探针未通过：代理类客户端（Claude Code / opencode 等）在此模型上调工具会卡死。常见原因为路由前缀错配走了 litellm 翻译层（对照表 provider_prefix_map 缺行或凭证方言与前缀不符），请核对供应商类型与凭证格式。
            </p>
          </template>
        </div>

        <!-- Thinking probe result -->
        <div v-if="thinkingProbeResult || thinkingProbeErrorMsg" class="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <label class="mb-2 block text-xs font-medium text-slate-500">Thinking 探针（{{ thinkingProbeResult?.protocol === 'anthropic' ? 'Anthropic' : 'OpenAI' }} 协议）</label>
          <div v-if="thinkingProbeErrorMsg" class="text-sm text-red-600">{{ thinkingProbeErrorMsg }}</div>
          <template v-else-if="thinkingProbeResult">
            <div v-if="thinkingProbeResult.error_detail" class="text-sm text-red-600">{{ thinkingProbeResult.error_detail.title || '探针无法执行' }}</div>
            <ul v-else class="space-y-1">
              <li v-for="v in thinkingProbeResult.verdicts" :key="v.turn" class="flex items-start gap-2 text-sm">
                <span :class="v.ok ? 'text-green-600' : 'text-red-600'">{{ v.ok ? '✓' : '✗' }}</span>
                <span class="font-medium text-slate-700">第 {{ v.turn }} 轮：</span>
                <span :class="v.ok ? 'text-slate-600' : 'text-red-600'">{{ v.detail }}</span>
              </li>
            </ul>
            <p v-if="!thinkingProbeResult.success && !thinkingProbeResult.error_detail" class="mt-2 text-xs leading-5 text-amber-700">
              Thinking 探针未通过：多轮思考对话在此模型上会失败（签名被翻译层剥除或 thinking 参数未被透传）。常见于跨方言翻译路径（anthropic 入口 + openai 方言凭证裸名组），请核对凭证格式与路由前缀。
            </p>
          </template>
        </div>

        <!-- History replay probe result -->
        <div v-if="historyProbeResult || historyProbeErrorMsg" class="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <label class="mb-2 block text-xs font-medium text-slate-500">历史回放探针（{{ historyProbeResult?.protocol === 'anthropic' ? 'Anthropic' : 'OpenAI' }} 协议）</label>
          <div v-if="historyProbeErrorMsg" class="text-sm text-red-600">{{ historyProbeErrorMsg }}</div>
          <template v-else-if="historyProbeResult">
            <div v-if="historyProbeResult.error_detail" class="text-sm text-red-600">{{ historyProbeResult.error_detail.title || '探针无法执行' }}</div>
            <template v-else>
              <p class="mb-2 text-xs text-slate-500">回放目标：{{ historyProbeResult.replay_model }}</p>
              <ul class="space-y-1">
                <li v-for="v in historyProbeResult.verdicts" :key="v.turn" class="flex items-start gap-2 text-sm">
                  <span :class="v.ok ? 'text-green-600' : 'text-red-600'">{{ v.ok ? '✓' : '✗' }}</span>
                  <span class="font-medium text-slate-700">第 {{ v.turn }} 轮：</span>
                  <span :class="v.ok ? 'text-slate-600' : 'text-red-600'">{{ v.detail }}</span>
                </li>
              </ul>
              <p v-if="!historyProbeResult.success" class="mt-2 text-xs leading-5 text-amber-700">
                历史回放未通过：携带 thinking / 工具结果的历史在切换模型后可能被拒。网关会对 400/422 自动剥离别家签发的思考状态并重试一次；仍失败请新开会话。
              </p>
            </template>
          </template>
        </div>

        <!-- Prompt cache probe result -->
        <div v-if="cacheProbeResult || cacheProbeErrorMsg" class="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <label class="mb-2 block text-xs font-medium text-slate-500">Prompt Cache 探针（{{ cacheProbeResult?.protocol === 'anthropic' ? 'Anthropic' : 'OpenAI' }} 协议）</label>
          <div v-if="cacheProbeErrorMsg" class="text-sm text-red-600">{{ cacheProbeErrorMsg }}</div>
          <template v-else-if="cacheProbeResult">
            <div v-if="cacheProbeResult.error_detail" class="text-sm text-red-600">{{ cacheProbeResult.error_detail.title || '探针无法执行' }}</div>
            <template v-else>
              <ul class="space-y-1">
                <li v-for="v in cacheProbeResult.verdicts" :key="v.turn" class="flex items-start gap-2 text-sm">
                  <span :class="v.ok ? 'text-green-600' : 'text-red-600'">{{ v.ok ? '✓' : '✗' }}</span>
                  <span class="font-medium text-slate-700">第 {{ v.turn }} 轮：</span>
                  <span :class="v.ok ? 'text-slate-600' : 'text-red-600'">{{ v.detail }}</span>
                </li>
              </ul>
              <p v-if="!cacheProbeResult.success" class="mt-2 text-xs leading-5 text-amber-700">
                缓存未命中：客户端 cache_control 断点可能被翻译层丢弃，或供应商不支持前缀缓存。长时间对话成本会显著上升。
              </p>
            </template>
          </template>
        </div>

        <!-- Output area -->
        <div v-if="outputContent || errorMsg" class="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <label class="mb-2 block text-xs font-medium text-slate-500">测试结果</label>
          <div v-if="errorMsg" class="space-y-2">
            <div class="text-sm font-medium text-red-600">{{ errorDetail?.title || errorMsg }}</div>
            <div v-if="errorDetail?.message" class="text-sm leading-6 text-slate-600">{{ errorDetail.message }}</div>
            <div
              v-if="canResyncAnthropicAccess"
              class="rounded-lg border border-amber-200 bg-amber-50 p-3"
            >
              <p class="mb-2 text-xs leading-5 text-amber-700">
                若已确认上游供应商已开通该模型仍测试失败，可能是平台与 LiteLLM 的授权未同步，点击重新同步后重试。
              </p>
              <button
                type="button"
                :disabled="isResyncingAnthropic"
                class="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-60"
                @click="handleResyncAnthropicAccess"
              >
                {{ isResyncingAnthropic ? '同步中...' : '重新同步模型授权' }}
              </button>
            </div>
            <button
              v-if="errorDetail?.technical_detail"
              type="button"
              class="text-xs font-medium text-slate-500 hover:text-slate-700"
              @click="showTechnicalDetail = !showTechnicalDetail"
            >
              {{ showTechnicalDetail ? '收起技术详情' : '查看技术详情' }}
            </button>
            <pre
              v-if="showTechnicalDetail && errorDetail?.technical_detail"
              class="max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs text-slate-500"
            >{{ errorDetail.technical_detail }}</pre>
          </div>
          <div v-else class="whitespace-pre-wrap text-sm text-slate-800">{{ outputContent }}<span v-if="isStreaming" class="inline-block h-4 w-1.5 animate-pulse bg-slate-400" /></div>
        </div>
      </div>
    </div>
  </div>
</template>
