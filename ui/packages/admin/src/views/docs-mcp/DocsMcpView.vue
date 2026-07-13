<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import {
  getDocsMcpStats,
  getDocsMcpJobs,
  getDocsMcpLibraries,
  createDocsMcpJob,
  cancelDocsMcpJob,
  clearCompletedDocsMcpJobs,
  getDocsMcpEventSourceUrl,
  toast,
  type DocsMcpStats,
  type DocsMcpJob,
  type DocsMcpLibrary,
  type DocsMcpCreateJobParams,
} from '@aihelms/shared'
import { RefreshCw, Loader2 } from 'lucide-vue-next'
import AnalyticsCards from './components/AnalyticsCards.vue'
import JobList from './components/JobList.vue'
import LibraryList from './components/LibraryList.vue'
import ScrapeJobDialog from './components/ScrapeJobDialog.vue'

const stats = ref<DocsMcpStats | null>(null)
const jobs = ref<DocsMcpJob[]>([])
const libraries = ref<DocsMcpLibrary[]>([])
const loading = ref(false)
const showScrapeDialog = ref(false)
let eventSource: EventSource | null = null

async function loadAll(): Promise<void> {
  loading.value = true
  try {
    const [statsRes, jobsRes, libsRes] = await Promise.all([
      getDocsMcpStats(),
      getDocsMcpJobs(),
      getDocsMcpLibraries(),
    ])
    stats.value = statsRes
    jobs.value = jobsRes
    libraries.value = libsRes
  } catch (e) {
    toast.error((e as Error).message || '加载数据失败')
  } finally {
    loading.value = false
  }
}

function connectSSE(): void {
  const url = getDocsMcpEventSourceUrl()
  eventSource = new EventSource(url)
  eventSource.addEventListener('job-status-change', () => {
    loadJobs()
  })
  eventSource.addEventListener('job-progress', () => {
    loadJobs()
  })
  eventSource.addEventListener('job-list-change', () => {
    loadJobs()
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

async function loadJobs(): Promise<void> {
  try {
    jobs.value = await getDocsMcpJobs()
  } catch { /* silent */ }
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

async function handleCancelJob(jobId: string): Promise<void> {
  try {
    await cancelDocsMcpJob(jobId)
    toast.success('任务已取消')
    await loadJobs()
  } catch (e) {
    toast.error((e as Error).message || '取消失败')
  }
}

async function handleClearCompleted(): Promise<void> {
  try {
    await clearCompletedDocsMcpJobs()
    toast.success('已清理完成任务')
    await loadJobs()
  } catch (e) {
    toast.error((e as Error).message || '清理失败')
  }
}

async function handleSubmitJob(params: DocsMcpCreateJobParams): Promise<void> {
  try {
    await createDocsMcpJob(params)
    toast.success('爬取任务已创建')
    showScrapeDialog.value = false
    await loadJobs()
  } catch (e) {
    toast.error((e as Error).message || '创建失败')
  }
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
      <button
        class="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
        :disabled="loading"
        @click="loadAll"
      >
        <Loader2 v-if="loading" class="h-4 w-4 animate-spin" />
        <RefreshCw v-else class="h-4 w-4" />
        刷新
      </button>
    </div>

    <AnalyticsCards :stats="stats" />

    <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <JobList
        :jobs="jobs"
        @cancel="handleCancelJob"
        @clear-completed="handleClearCompleted"
      />
      <LibraryList
        :libraries="libraries"
        @add-job="showScrapeDialog = true"
      />
    </div>

    <ScrapeJobDialog
      :visible="showScrapeDialog"
      @close="showScrapeDialog = false"
      @submit="handleSubmitJob"
    />
  </div>
</template>
