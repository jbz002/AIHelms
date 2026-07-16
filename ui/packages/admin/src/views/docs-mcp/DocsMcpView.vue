<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import {
  getDocsMcpStats,
  getDocsMcpLibraries,
  createCrawlTask,
  getDocsMcpEventSourceUrl,
  fetchDocsMcpUrl,
  toast,
  type DocsMcpStats,
  type DocsMcpLibrary,
  type DocsMcpScrapeOptions,
} from '@aihelms/shared'
import { Loader2, Globe, Copy, X, ChevronDown, Plus, Upload } from 'lucide-vue-next'
import AnalyticsCards from './components/AnalyticsCards.vue'
import LibraryList from './components/LibraryList.vue'
import ScrapeJobDialog from './components/ScrapeJobDialog.vue'
import UploadDialog from './components/UploadDialog.vue'
import TaskRecordList from './components/TaskRecordList.vue'

const stats = ref<DocsMcpStats | null>(null)
const libraries = ref<DocsMcpLibrary[]>([])
const showScrapeDialog = ref(false)
const showUploadDialog = ref(false)
const taskRecordListRef = ref<InstanceType<typeof TaskRecordList> | null>(null)
let eventSource: EventSource | null = null

// Fetch URL state
const fetchUrl = ref('')
const fetchLoading = ref(false)
const fetchResult = ref<string | null>(null)
const fetchExpanded = ref(false)

async function handleFetchUrl(): Promise<void> {
  const url = fetchUrl.value.trim()
  if (!url) return
  fetchLoading.value = true
  fetchResult.value = null
  fetchExpanded.value = false
  try {
    const result = await fetchDocsMcpUrl(url)
    fetchResult.value = result.content
    fetchExpanded.value = true
  } catch (e) {
    toast.error((e as Error).message || '抓取失败')
  } finally {
    fetchLoading.value = false
  }
}

function copyResult(): void {
  if (!fetchResult.value) return
  navigator.clipboard.writeText(fetchResult.value).then(() => {
    toast.success('已复制到剪贴板')
  })
}

function closeResult(): void {
  fetchResult.value = null
  fetchExpanded.value = false
}

async function loadAll(): Promise<void> {
  try {
    const [statsRes, libsRes] = await Promise.all([
      getDocsMcpStats(),
      getDocsMcpLibraries(),
    ])
    stats.value = statsRes
    libraries.value = libsRes
  } catch (e) {
    toast.error((e as Error).message || '加载数据失败')
  }
}

function connectSSE(): void {
  const url = getDocsMcpEventSourceUrl()
  eventSource = new EventSource(url)
  eventSource.addEventListener('job-status-change', () => {
    loadLibraries()
    loadStats()
    taskRecordListRef.value?.loadTasks()
  })
  eventSource.addEventListener('job-progress', () => {
    loadLibraries()
  })
  eventSource.addEventListener('job-list-change', () => {
    loadLibraries()
    taskRecordListRef.value?.loadTasks()
  })
  eventSource.addEventListener('library-change', () => {
    loadLibraries()
    loadStats()
  })
  eventSource.onerror = () => {
    if (eventSource) {
      eventSource.close()
      setTimeout(connectSSE, 5000)
    }
  }
}

async function loadLibraries(): Promise<void> {
  try {
    libraries.value = await getDocsMcpLibraries()
  } catch { /* silent */ }
}

async function loadStats(): Promise<void> {
  try {
    stats.value = await getDocsMcpStats()
  } catch { /* silent */ }
}

async function handleSubmitJob(params: { url: string; library: string; version: string; options: DocsMcpScrapeOptions; ingestMode: string }): Promise<void> {
  try {
    await createCrawlTask({ url: params.url, library: params.library, version: params.version, options: params.options, auto_ingest: params.ingestMode === 'direct' })
    toast.success('爬取任务已创建')
    showScrapeDialog.value = false
    taskRecordListRef.value?.loadTasks()
  } catch (e) {
    toast.error((e as Error).message || '创建失败')
  }
}

async function handleUploaded(): Promise<void> {
  await loadLibraries()
  await loadStats()
  taskRecordListRef.value?.loadTasks()
}

onMounted(() => {
  loadAll()
  connectSSE()
})

onUnmounted(() => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-gray-900">API文档管理</h1>
      <div class="flex items-center gap-2">
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          @click="showScrapeDialog = true"
        >
          <Plus class="h-4 w-4" />
          新建文档
        </button>
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
          @click="showUploadDialog = true"
        >
          <Upload class="h-4 w-4" />
          上传文档
        </button>
      </div>
    </div>

    <AnalyticsCards :stats="stats" />

    <!-- Fetch URL -->
    <div class="rounded-lg border border-gray-200 bg-white p-4">
      <div class="flex items-center gap-3">
        <div class="relative flex-1">
          <Globe class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            v-model="fetchUrl"
            type="text"
            placeholder="输入 URL，抓取网页内容并转为 Markdown..."
            class="w-full rounded-md border border-gray-300 py-2.5 pl-10 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            @keyup.enter="handleFetchUrl"
          />
        </div>
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          :disabled="!fetchUrl.trim() || fetchLoading"
          @click="handleFetchUrl"
        >
          <Loader2 v-if="fetchLoading" class="h-4 w-4 animate-spin" />
          <Globe v-else class="h-4 w-4" />
          抓取
        </button>
      </div>

      <!-- Result preview -->
      <div v-if="fetchResult !== null" class="mt-3 border-t border-gray-200 pt-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5 text-sm text-gray-500">
            <ChevronDown class="h-4 w-4" />
            <span>抓取结果（{{ fetchResult.length }} 字符）</span>
          </div>
          <div class="flex items-center gap-1">
            <button
              class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
              @click="fetchExpanded = !fetchExpanded"
            >
              {{ fetchExpanded ? '收起' : '展开' }}
              <ChevronDown class="h-3 w-3 transition-transform" :class="{ 'rotate-180': fetchExpanded }" />
            </button>
            <button
              class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
              @click="copyResult"
            >
              <Copy class="h-3 w-3" />
              复制
            </button>
            <button
              class="inline-flex items-center rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
              @click="closeResult"
            >
              <X class="h-3 w-3" />
            </button>
          </div>
        </div>
        <pre
          v-show="fetchExpanded"
          class="mt-2 max-h-96 overflow-auto rounded-md bg-gray-50 p-3 text-xs leading-relaxed text-gray-700 whitespace-pre-wrap break-words"
        >{{ fetchResult }}</pre>
      </div>
    </div>

    <TaskRecordList ref="taskRecordListRef" @refresh="loadLibraries(); loadStats()" />

    <LibraryList :libraries="libraries" />

    <ScrapeJobDialog
      :visible="showScrapeDialog"
      @close="showScrapeDialog = false"
      @submit="handleSubmitJob"
    />
    <UploadDialog
      :visible="showUploadDialog"
      @close="showUploadDialog = false"
      @uploaded="handleUploaded"
    />
  </div>
</template>
