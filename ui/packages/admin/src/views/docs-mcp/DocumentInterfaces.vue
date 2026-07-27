<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiReference } from '@scalar/api-reference'
import '@scalar/api-reference/style.css'
import type { ActiveModel, Document, DocumentApiExtractStatus } from '@aihelms/shared'
import {
  extractDocumentInterfaces,
  getActiveModels,
  getDocument,
  getDocumentExtractStatus,
  getDocumentSpec,
  toast,
} from '@aihelms/shared'
import { ArrowLeft, Loader2, RefreshCw, Wand2, Code2 } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const libraryName = computed(() => route.params.libraryName as string)
const docId = computed(() => Number(route.params.docId))

const doc = ref<Document | null>(null)
const spec = ref<Record<string, unknown> | null>(null)
const status = ref<DocumentApiExtractStatus | null>(null)
const models = ref<ActiveModel[]>([])
const loading = ref(false)
const submitting = ref(false)
const showPicker = ref(false)
const selectedModelId = ref<number | null>(null)
let pollTimer: number | null = null

const hasEndpoints = computed(() => Object.keys((spec.value?.paths as object) ?? {}).length > 0)
const isExtracting = computed(
  () => status.value?.status === 'queued' || status.value?.status === 'running',
)
const isFailed = computed(() => status.value?.status === 'failed')
const progress = computed(() => status.value?.summary?.progress)

async function loadAll(): Promise<void> {
  loading.value = true
  try {
    const [docRes, specRes, statusRes, modelRes] = await Promise.all([
      getDocument(docId.value),
      getDocumentSpec(docId.value),
      getDocumentExtractStatus(docId.value),
      getActiveModels(),
    ])
    doc.value = docRes
    spec.value = specRes
    status.value = statusRes
    models.value = modelRes
    if (statusRes && (statusRes.status === 'queued' || statusRes.status === 'running')) {
      startPolling()
    }
  } catch (e) {
    toast.error((e as Error).message || '加载失败')
  } finally {
    loading.value = false
  }
}

function startPolling(): void {
  stopPolling()
  pollTimer = window.setInterval(pollOnce, 5000)
}

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollOnce(): Promise<void> {
  try {
    const latest = await getDocumentExtractStatus(docId.value)
    status.value = latest
    if (!latest || !isExtracting.value) {
      stopPolling()
      if (latest?.status === 'completed') {
        spec.value = await getDocumentSpec(docId.value)
        toast.success(`提取完成，共 ${latest.endpoint_count} 个接口`)
      } else if (latest?.status === 'failed') {
        toast.error('接口提取失败')
      }
    }
  } catch (e) {
    stopPolling()
    toast.error((e as Error).message || '轮询状态失败')
  }
}

function openPicker(): void {
  if (!models.value.length) {
    toast.error('无可用模型，请先在模型管理中启用模型')
    return
  }
  selectedModelId.value = models.value[0].id
  showPicker.value = true
}

async function confirmExtract(): Promise<void> {
  if (selectedModelId.value === null || submitting.value) return
  submitting.value = true
  try {
    const result = await extractDocumentInterfaces(docId.value, selectedModelId.value)
    status.value = result
    showPicker.value = false
    startPolling()
    toast.success('接口提取任务已提交')
  } catch (e) {
    toast.error((e as Error).message || '提交提取任务失败')
  } finally {
    submitting.value = false
  }
}

onMounted(loadAll)
onUnmounted(stopPolling)
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-3">
      <button
        class="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        @click="router.push({ name: 'DocumentDetail', params: { libraryName, docId } })"
      >
        <ArrowLeft class="h-4 w-4" />
      </button>
      <h2 class="text-lg font-semibold text-gray-900 truncate">
        接口调试 · {{ doc?.title || `文档 #${docId}` }}
      </h2>
      <div class="ml-auto flex items-center gap-2">
        <span v-if="status" class="text-xs text-gray-500">
          {{ { queued: '排队中', running: '提取中', completed: `已提取 ${status.endpoint_count} 个`, failed: '提取失败' }[status.status] }}
        </span>
        <button
          v-if="!isExtracting && !showPicker"
          class="flex items-center gap-1 rounded-md bg-purple-50 px-3 py-1.5 text-xs font-medium text-purple-700 hover:bg-purple-100"
          @click="openPicker"
        >
          <Wand2 v-if="!hasEndpoints" class="h-3 w-3" />
          <RefreshCw v-else class="h-3 w-3" />
          {{ hasEndpoints ? '重新提取' : '提取接口' }}
        </button>
      </div>
    </div>

    <div v-if="showPicker" class="rounded-lg border border-gray-200 bg-white p-4">
      <div class="flex items-end gap-3">
        <div class="flex-1">
          <label class="mb-1 block text-xs font-medium text-gray-600">选择提取模型</label>
          <select
            v-model.number="selectedModelId"
            class="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-purple-500 focus:outline-none"
          >
            <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}</option>
          </select>
        </div>
        <button
          class="flex items-center gap-1 rounded-md bg-purple-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          :disabled="submitting"
          @click="confirmExtract"
        >
          <Loader2 v-if="submitting" class="h-3 w-3 animate-spin" />
          开始提取
        </button>
        <button
          class="rounded-md bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-200"
          @click="showPicker = false"
        >
          取消
        </button>
      </div>
    </div>

    <div v-if="loading" class="flex h-[60vh] items-center justify-center">
      <Loader2 class="h-6 w-6 animate-spin text-gray-400" />
    </div>

    <div
      v-else-if="isExtracting"
      class="flex h-[60vh] flex-col items-center justify-center rounded-lg border border-gray-200 bg-white"
    >
      <Loader2 class="h-8 w-8 animate-spin text-purple-500" />
      <p class="mt-3 text-sm text-gray-600">{{ progress?.step || '处理中' }}…</p>
      <p v-if="status?.model_name" class="mt-1 text-xs text-gray-400">{{ status.model_name }}</p>
    </div>

    <div
      v-else-if="!hasEndpoints"
      class="flex h-[60vh] flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 bg-white"
    >
      <template v-if="isFailed">
        <p class="text-sm text-red-600">接口提取失败</p>
        <p v-if="status?.error_message" class="mt-1 max-w-md text-center text-xs text-gray-500">
          {{ status.error_message }}
        </p>
      </template>
      <template v-else>
        <Code2 class="h-10 w-10 text-gray-300" />
        <p class="mt-3 text-sm text-gray-500">尚未提取接口</p>
      </template>
      <button
        class="mt-4 flex items-center gap-1 rounded-md bg-purple-50 px-3 py-1.5 text-xs font-medium text-purple-700 hover:bg-purple-100"
        @click="openPicker"
      >
        <Wand2 class="h-3 w-3" />
        提取接口
      </button>
    </div>

    <div
      v-else
      class="scalar-host h-[calc(100vh-8rem)] overflow-hidden rounded-lg border border-gray-200 bg-white"
    >
      <ApiReference
        :configuration="{
          content: spec,
          layout: 'modern',
          localization: { locale: 'zh-CN' },
        }"
      />
    </div>
  </div>
</template>

<style scoped>
/*
 仅覆写 scalar 主题变量，使 scalar 面板的字号/强调色/文字色/圆角与本系统周围页面对齐。
 scalar 默认正文 16px、accent #09f 蓝、中性灰文字，与本模块（text-sm 14px、purple-600 紫色、gray 标度）不一致。
 scalar UI 仅支持 CSS 变量定制，无 Tailwind 等价写法，故破例用 scoped style。
*/
.scalar-host {
  --scalar-font: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
    'Helvetica Neue', Arial, 'Noto Sans', sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji',
    'Segoe UI Symbol', 'Noto Color Emoji';
  --scalar-font-code: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
  --scalar-font-size-2: 14px;
  --scalar-radius: 8px;
  --scalar-color-accent: #9333ea;
  --scalar-color-1: #111827;
  --scalar-color-2: #4b5563;
  --scalar-heading-1: 20px;
}
</style>
