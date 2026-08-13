<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type {
  LibraryEndpoint,
  LibraryInterfacesResult,
  LibraryBatchExtractStatus,
  LibraryClassifyStatus,
} from '@aihelms/shared'
import {
  getLibraryInterfaces,
  extractLibraryInterfaces,
  getLibraryExtractStatus,
  getLibraryClassifyStatus,
  toast,
} from '@aihelms/shared'
import { ArrowLeft, Loader2, Code2, Wand2 } from 'lucide-vue-next'
import LibraryEndpointList from './interface-debugger/LibraryEndpointList.vue'
import OperationDetail from './interface-debugger/OperationDetail.vue'
import ExtractConfirmDialog from './components/ExtractConfirmDialog.vue'

const route = useRoute()
const router = useRouter()
const libraryName = computed(() => route.params.libraryName as string)

const loading = ref(false)
const result = ref<LibraryInterfacesResult | null>(null)
const selectedKey = ref<string | null>(null)

const submitting = ref(false)
const showExtractConfirm = ref(false)
const batchStatus = ref<LibraryBatchExtractStatus | null>(null)
const classifyStatus = ref<LibraryClassifyStatus | null>(null)
let batchTimer: number | null = null
let classifyTimer: number | null = null

const isBatchRunning = computed(
  () => batchStatus.value?.status === 'queued' || batchStatus.value?.status === 'running',
)
const isClassifyRunning = computed(
  () => classifyStatus.value?.status === 'queued' || classifyStatus.value?.status === 'running',
)
const isBusy = computed(() => isBatchRunning.value || isClassifyRunning.value || submitting.value)

// 库是否已提取过：有接口或有过完成的批量任务。用于按钮文案区分首次提取与增量更新
const hasExtracted = computed(
  () =>
    (result.value?.endpoints?.length ?? 0) > 0 ||
    batchStatus.value?.finished_at != null,
)
const batchTitle = computed(() => {
  const hint = '仅提取新增/变更文档，未变更的自动跳过'
  const b = batchStatus.value
  if (b?.finished_at) {
    return `${hint}\n上次：${b.total_documents} 文档 / ${b.total_endpoints} 接口 / 跳过 ${b.skipped_documents ?? 0}`
  }
  return hint
})

const items = computed(() =>
  (result.value?.endpoints ?? []).map((e) => ({
    key: String(e.id),
    method: e.method,
    path: e.path,
    summary: e.summary,
    category: e.category,
  })),
)
const selected = computed<LibraryEndpoint | null>(
  () => result.value?.endpoints.find((e) => String(e.id) === selectedKey.value) ?? null,
)

async function load(): Promise<void> {
  loading.value = true
  try {
    result.value = await getLibraryInterfaces(libraryName.value)
    if (result.value.endpoints.length && !selectedKey.value) {
      selectedKey.value = String(result.value.endpoints[0].id)
    }
  } catch (e) {
    toast.error((e as Error).message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function confirmBatchExtract(force = false): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  try {
    batchStatus.value = await extractLibraryInterfaces(libraryName.value, force)
    startBatchPoll()
    toast.success('批量提取任务已提交，完成后将自动分类')
  } catch (e) {
    toast.error((e as Error).message || '提交批量提取失败')
  } finally {
    submitting.value = false
  }
}

async function onConfirmExtract(force = false): Promise<void> {
  showExtractConfirm.value = false
  await confirmBatchExtract(force)
}

function startBatchPoll(): void {
  stopBatchPoll()
  batchTimer = window.setInterval(pollBatch, 5000)
}

function stopBatchPoll(): void {
  if (batchTimer !== null) {
    window.clearInterval(batchTimer)
    batchTimer = null
  }
}

async function pollBatch(): Promise<void> {
  try {
    const latest = await getLibraryExtractStatus(libraryName.value)
    batchStatus.value = latest
    if (!latest || !isBatchRunning.value) {
      stopBatchPoll()
      if (latest?.status === 'completed') {
        const skip = latest.skipped_documents ?? 0
        toast.success(
          `批量提取完成，共 ${latest.total_endpoints} 个接口${skip ? `，跳过 ${skip} 个未变更文档` : ''}`,
        )
        await load()
        if ((latest.total_endpoints ?? 0) > 0) {
          startClassifyPoll()
        }
      } else if (latest?.status === 'failed') {
        toast.error('批量提取失败')
      }
    }
  } catch {
    stopBatchPoll()
  }
}

function startClassifyPoll(): void {
  stopClassifyPoll()
  classifyTimer = window.setInterval(pollClassify, 5000)
}

function stopClassifyPoll(): void {
  if (classifyTimer !== null) {
    window.clearInterval(classifyTimer)
    classifyTimer = null
  }
}

async function pollClassify(): Promise<void> {
  try {
    const latest = await getLibraryClassifyStatus(libraryName.value)
    classifyStatus.value = latest
    if (!latest) {
      stopClassifyPoll()
      return
    }
    if (latest.status === 'queued' || latest.status === 'running') return
    stopClassifyPoll()
    if (latest.status === 'completed') {
      toast.success(`接口分类完成，共 ${latest.category_count} 个分类`)
    } else if (latest.status === 'failed') {
      toast.error('接口分类失败')
    }
    await load()
  } catch {
    stopClassifyPoll()
  }
}

onMounted(() => {
  load()
  getLibraryExtractStatus(libraryName.value).then((s) => {
    batchStatus.value = s
    if (s && (s.status === 'queued' || s.status === 'running')) startBatchPoll()
  })
  getLibraryClassifyStatus(libraryName.value).then((s) => {
    classifyStatus.value = s
    if (s && (s.status === 'queued' || s.status === 'running')) startClassifyPoll()
  })
})

onUnmounted(() => {
  stopBatchPoll()
  stopClassifyPoll()
})
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-3">
      <button
        class="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        @click="router.push({ name: 'DocumentList', params: { libraryName } })"
      >
        <ArrowLeft class="h-4 w-4" />
      </button>
      <h2 class="text-lg font-semibold text-gray-900 truncate">
        接口总览 · {{ libraryName }}
      </h2>
      <span v-if="result" class="text-xs text-gray-500">共 {{ result.total }} 个接口</span>
      <div class="ml-auto flex items-center gap-2">
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-60"
          :disabled="isBusy"
          :title="batchTitle"
          @click="showExtractConfirm = true"
        >
          <Loader2 v-if="isBatchRunning || submitting" class="h-4 w-4 animate-spin" />
          <Wand2 v-else class="h-4 w-4" />
          {{ isBatchRunning ? `提取中 ${batchStatus?.completed_documents ?? 0}/${batchStatus?.total_documents ?? 0}` : (hasExtracted ? '更新接口' : '批量提取接口') }}
        </button>
        <span v-if="isClassifyRunning" class="inline-flex items-center gap-1 text-xs text-indigo-600">
          <Loader2 class="h-3.5 w-3.5 animate-spin" />
          分类中
        </span>
      </div>
    </div>

    <div v-if="loading" class="flex h-[60vh] items-center justify-center">
      <Loader2 class="h-6 w-6 animate-spin text-gray-400" />
    </div>

    <div
      v-else-if="!result || !result.endpoints.length"
      class="flex h-[60vh] flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 bg-white"
    >
      <Code2 class="h-10 w-10 text-gray-300" />
      <p class="mt-3 text-sm text-gray-500">该库尚未提取接口，请点击右上角「批量提取接口」</p>
    </div>

    <div v-else class="flex h-[calc(100vh-8rem)] gap-4 overflow-hidden">
      <div class="flex w-80 shrink-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <LibraryEndpointList :endpoints="items" :selected-key="selectedKey" @select="selectedKey = $event" />
      </div>
      <div class="flex flex-1 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <OperationDetail
          v-if="selected"
          :method="selected.method"
          :path="selected.path"
          :operation="selected.operation"
          :doc-id="selected.document_id"
          :library-name="libraryName"
          :base-url="selected.base_url"
        />
        <div v-else class="flex h-full items-center justify-center text-sm text-slate-400">
          请从左侧选择接口
        </div>
      </div>
    </div>

    <ExtractConfirmDialog
      :visible="showExtractConfirm"
      :library-name="libraryName"
      @close="showExtractConfirm = false"
      @confirm="onConfirmExtract"
    />
  </div>
</template>
