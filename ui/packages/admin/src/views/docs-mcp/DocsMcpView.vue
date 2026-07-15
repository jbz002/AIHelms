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
  fetchDocsMcpUrl,
  toast,
  type DocsMcpStats,
  type DocsMcpJob,
  type DocsMcpLibrary,
  type DocsMcpCreateJobParams,
} from '@aihelms/shared'
import { RefreshCw, Loader2, Globe, Copy, X, ChevronDown } from 'lucide-vue-next'
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
