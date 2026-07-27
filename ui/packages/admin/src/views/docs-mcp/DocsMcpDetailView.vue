<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getDocsMcpLibraryDetail,
  searchDocsMcp,
  deleteDocsMcpVersion,
  deleteDocsMcpVersionDocuments,
  createCrawlTask,
  getDocsMcpEventSourceUrl,
  toast,
  type DocsMcpLibrary,
  type DocsMcpSearchResult,
  type DocsMcpScrapeOptions,
} from '@aihelms/shared'
import { ArrowLeft, ExternalLink, Plus, Loader2 } from 'lucide-vue-next'
import SearchCard from './components/SearchCard.vue'
import SearchResultList from './components/SearchResultList.vue'
import VersionRow from './components/VersionRow.vue'
import ScrapeJobDialog from './components/ScrapeJobDialog.vue'
import TaskRecordList from './components/TaskRecordList.vue'

const route = useRoute()
const router = useRouter()
const libraryName = route.params.libraryName as string

const library = ref<DocsMcpLibrary | null>(null)
const searchResults = ref<DocsMcpSearchResult[]>([])
const searchLoading = ref(false)
const hasSearched = ref(false)
const loading = ref(false)
const showAddVersionDialog = ref(false)
const taskRecordListRef = ref<InstanceType<typeof TaskRecordList> | null>(null)
let eventSource: EventSource | null = null

async function loadLibrary(): Promise<void> {
  loading.value = true
  try {
    library.value = await getDocsMcpLibraryDetail(libraryName)
  } catch (e) {
    toast.error((e as Error).message || '加载文档库失败')
  } finally {
    loading.value = false
  }
}

async function handleSearch(query: string, version: string | null): Promise<void> {
  searchLoading.value = true
  hasSearched.value = true
  try {
    searchResults.value = await searchDocsMcp(
      libraryName,
      query,
      version || undefined,
      20,
    )
  } catch (e) {
    toast.error((e as Error).message || '搜索失败')
  } finally {
    searchLoading.value = false
  }
}

async function handleDeleteVersion(_library: string, version: string): Promise<void> {
  const wasLastVersion = (library.value?.versions.length ?? 0) <= 1
  try {
    await deleteDocsMcpVersion(libraryName, version)
    toast.success(wasLastVersion ? '文档库已删除' : '版本已删除')
    if (wasLastVersion) {
      goBack()
    } else {
      await loadLibrary()
    }
  } catch (e) {
    toast.error((e as Error).message || '删除失败')
  }
}

async function handleClearDocuments(_library: string, version: string): Promise<void> {
  try {
    await deleteDocsMcpVersionDocuments(libraryName, version)
    toast.success('文档已清除，可重新抓取')
    await loadLibrary()
  } catch (e) {
    toast.error((e as Error).message || '清除失败')
  }
}

function goBack(): void {
  router.push({ name: 'DocsMcp' })
}

async function handleSubmitJob(params: {
  url: string
  library: string
  version: string
  options: DocsMcpScrapeOptions
  ingestMode: string
}): Promise<void> {
  try {
    await createCrawlTask({
      url: params.url,
      library: params.library,
      version: params.version,
      options: params.options,
      auto_ingest: params.ingestMode === 'direct',
    })
    toast.success('爬取任务已创建')
    showAddVersionDialog.value = false
    await loadLibrary()
    taskRecordListRef.value?.loadTasks()
  } catch (e) {
    toast.error((e as Error).message || '创建失败')
  }
}

function connectSSE(): void {
  const url = getDocsMcpEventSourceUrl()
  eventSource = new EventSource(url)
  eventSource.addEventListener('job-status-change', () => {
    loadLibrary()
    taskRecordListRef.value?.loadTasks()
  })
  eventSource.addEventListener('job-progress', () => {
    loadLibrary()
    taskRecordListRef.value?.loadTasks()
  })
  eventSource.addEventListener('job-list-change', () => {
    loadLibrary()
    taskRecordListRef.value?.loadTasks()
  })
  eventSource.onerror = () => {
    if (eventSource) {
      eventSource.close()
      setTimeout(connectSSE, 5000)
    }
  }
}

onMounted(() => {
  loadLibrary()
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
    <div class="flex items-center gap-3">
      <button
        class="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        @click="goBack"
      >
        <ArrowLeft class="h-5 w-5" />
      </button>
      <div v-if="library" class="min-w-0 flex-1">
        <h1 class="truncate text-xl font-bold text-gray-900">{{ libraryName }}</h1>
        <a
          v-if="library.versions.length > 0 && library.versions[0].sourceUrl"
          :href="library.versions[0].sourceUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700"
        >
          {{ library.versions[0].sourceUrl }}
          <ExternalLink class="h-3 w-3" />
        </a>
      </div>
      <button
        class="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        @click="showAddVersionDialog = true"
      >
        <Plus class="h-4 w-4" />
        新增版本
      </button>
    </div>

    <Loader2 v-if="loading" class="mx-auto h-8 w-8 animate-spin text-gray-300" />

    <template v-if="library">
      <SearchCard :versions="library.versions" @search="handleSearch" />
      <SearchResultList v-if="hasSearched" :results="searchResults" :loading="searchLoading" />

      <div class="rounded-lg border border-gray-200 bg-white p-4">
        <h3 class="mb-3 text-sm font-semibold text-gray-700">
          版本列表
          <span class="font-normal text-gray-400">({{ library.versions.length }})</span>
        </h3>
        <div v-if="library.versions.length === 0" class="rounded-lg border border-dashed border-gray-200 py-6 text-center">
          <p class="text-sm text-gray-400">暂无版本</p>
        </div>
        <div v-else class="space-y-2">
          <VersionRow
            v-for="ver in library.versions"
            :key="ver.ref.version || '_default'"
            :version="ver"
            :library-name="libraryName"
            :is-last-version="library.versions.length === 1"
            @delete="handleDeleteVersion"
            @clear-documents="handleClearDocuments"
            @view-documents="(lib, ver) => router.push({ name: 'DocumentList', params: { libraryName: lib }, query: { version: ver } })"
          />
        </div>
      </div>

      <TaskRecordList
        v-if="library"
        :library-name="libraryName"
        ref="taskRecordListRef"
        @refresh="loadLibrary()"
      />
    </template>

    <ScrapeJobDialog
      :visible="showAddVersionDialog"
      :default-library="libraryName"
      @close="showAddVersionDialog = false"
      @submit="handleSubmitJob"
    />
  </div>
</template>
