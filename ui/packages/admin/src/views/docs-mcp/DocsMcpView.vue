<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  getDocsMcpStats,
  getDocsMcpLibraries,
  getDocumentDashboardSummary,
  createCrawlTask,
  getDocsMcpEventSourceUrl,
  toast,
  type DocsMcpStats,
  type DocsMcpLibrary,
  type DocsMcpScrapeOptions,
  type DocumentDashboardSummary,
} from '@aihelms/shared'
import { Plus, Upload, Globe } from 'lucide-vue-next'
import AnalyticsCards from './components/AnalyticsCards.vue'
import LibraryList from './components/LibraryList.vue'
import LibraryFilterBar from './components/LibraryFilterBar.vue'
import FetchUrlPanel from './components/FetchUrlPanel.vue'
import ScrapeJobDialog from './components/ScrapeJobDialog.vue'
import UploadDialog from './components/UploadDialog.vue'
import TaskRecordList from './components/TaskRecordList.vue'

const stats = ref<DocsMcpStats | null>(null)
const libraries = ref<DocsMcpLibrary[]>([])
const summary = ref<DocumentDashboardSummary | null>(null)
const libraryNameQuery = ref('')
const statusFilter = ref<string>('')
const showScrapeDialog = ref(false)
const showUploadDialog = ref(false)
const showFetchDrawer = ref(false)
const taskRecordListRef = ref<InstanceType<typeof TaskRecordList> | null>(null)
let eventSource: EventSource | null = null

async function loadAll(): Promise<void> {
  try {
    const [statsRes, libsRes, summaryRes] = await Promise.all([
      getDocsMcpStats(),
      getDocsMcpLibraries(),
      getDocumentDashboardSummary(),
    ])
    stats.value = statsRes
    libraries.value = libsRes
    summary.value = summaryRes
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
    loadSummary()
    taskRecordListRef.value?.loadTasks()
  })
  eventSource.addEventListener('job-progress', () => {
    loadLibraries()
    taskRecordListRef.value?.loadTasks()
  })
  eventSource.addEventListener('job-list-change', () => {
    loadLibraries()
    taskRecordListRef.value?.loadTasks()
  })
  eventSource.addEventListener('library-change', () => {
    loadLibraries()
    loadStats()
    loadSummary()
    taskRecordListRef.value?.loadTasks()
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

async function loadSummary(): Promise<void> {
  try {
    summary.value = await getDocumentDashboardSummary()
  } catch { /* silent */ }
}

const filteredLibraries = computed(() => {
  const q = libraryNameQuery.value.trim().toLowerCase()
  const sf = statusFilter.value
  return libraries.value.filter((lib) => {
    if (q && !lib.library.toLowerCase().includes(q)) return false
    if (!sf) return true
    const bd = summary.value?.by_library[lib.library.toLowerCase()]
    if (!bd) return false
    if (sf === 'crawl' || sf === 'upload') return (bd.by_source[sf] ?? 0) > 0
    return (bd.by_status[sf] ?? 0) > 0
  })
})

async function handleSubmitJob(params: { url: string; library: string; version: string; options: DocsMcpScrapeOptions }): Promise<void> {
  try {
    await createCrawlTask({ url: params.url, library: params.library, version: params.version, options: params.options, auto_ingest: true })
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
  await loadSummary()
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
          class="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          @click="showFetchDrawer = true"
        >
          <Globe class="h-4 w-4" />
          抓取单页
        </button>
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          @click="showScrapeDialog = true"
        >
          <Plus class="h-4 w-4" />
          抓取文档
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

    <AnalyticsCards :stats="stats" :summary="summary" />

    <div class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-base font-semibold text-gray-900">文档列表</h2>
        <LibraryFilterBar
          v-model:query="libraryNameQuery"
          v-model:status="statusFilter"
          :total="libraries.length"
          :filtered-total="filteredLibraries.length"
        />
      </div>
      <LibraryList :libraries="filteredLibraries" />
    </div>

    <TaskRecordList ref="taskRecordListRef" @refresh="loadLibraries(); loadStats()" />

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
    <FetchUrlPanel :visible="showFetchDrawer" @close="showFetchDrawer = false" />
  </div>
</template>
