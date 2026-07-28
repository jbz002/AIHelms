<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type {
  Document,
  IngestStats,
  DocsMcpScrapeOptions,
  DocsMcpLibrary,
} from '@aihelms/shared'
import {
  getDocuments,
  getDocument,
  getDocumentStats,
  ingestDocument,
  ingestDocumentBatch,
  deleteDocument,
  createCrawlTask,
  getDocsMcpEventSourceUrl,
  getDocsMcpLibraryDetail,
  toast,
} from '@aihelms/shared'
import {
  ArrowLeft,
  Eye,
  Pencil,
  ArrowDownToLine,
  Trash2,
  Loader2,
  RefreshCw,
  BarChart3,
  Plus,
  Upload,
  Code2,
} from 'lucide-vue-next'
import ScrapeJobDialog from './components/ScrapeJobDialog.vue'
import UploadDialog from './components/UploadDialog.vue'
import SearchCard from './components/SearchCard.vue'
import DocSummary from './components/DocSummary.vue'

const route = useRoute()
const router = useRouter()
const libraryName = computed(() => route.params.libraryName as string)
const currentVersion = computed(() => (route.query.version as string) || '')

const documents = ref<Document[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const stats = ref<IngestStats | null>(null)
const sourceFilter = ref<string>('')
const statusFilter = ref<string>('')
const ingestingId = ref<number | null>(null)
const deletingId = ref<number | null>(null)
const batchIngesting = ref(false)
const showScrapeDialog = ref(false)
const showUploadDialog = ref(false)
const library = ref<DocsMcpLibrary | null>(null)
const libraryLoading = ref(false)
const activeQuery = ref('')
const searchNonce = ref(0)
const hasSearched = ref(false)
const showAddVersionDialog = ref(false)
let eventSource: EventSource | null = null

// 版本下拉：latest 持续锁定最新 + 库内全部版本
const versionOptions = computed(() => [
  { value: 'latest', label: '最新' },
  ...(library.value?.versions ?? []).map((v) => ({
    value: v.ref.version || '',
    label: v.ref.version || '默认',
  })),
])

// select v-model 代理：写时 router.replace 更新 query，读时取 currentVersion
const selectedVersion = computed<string>({
  get: () => currentVersion.value || 'latest',
  set: (val: string) => {
    router.replace({ query: { ...route.query, version: val } })
  },
})

const ingestStatusOptions = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待入库' },
  { value: 'ingesting', label: '入库中' },
  { value: 'ingested', label: '已入库' },
  { value: 'failed', label: '失败' },
  { value: 'duplicate', label: '触发重复' },
]

const sourceOptions = [
  { value: '', label: '全部来源' },
  { value: 'crawl', label: '爬虫' },
  { value: 'upload', label: '上传' },
]

const statusConfig: Record<string, { label: string; cls: string }> = {
  pending: { label: '待入库', cls: 'bg-yellow-100 text-yellow-700' },
  ingesting: { label: '入库中', cls: 'bg-blue-100 text-blue-700' },
  ingested: { label: '已入库', cls: 'bg-green-100 text-green-700' },
  failed: { label: '失败', cls: 'bg-red-100 text-red-700' },
  duplicate: { label: '触发重复', cls: 'bg-gray-100 text-gray-500' },
}

const pendingCount = computed(() => stats.value?.by_status?.pending ?? 0)

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 19)
}

async function loadDocuments(): Promise<void> {
  loading.value = true
  try {
    const res = await getDocuments(
      libraryName.value,
      sourceFilter.value || undefined,
      statusFilter.value || undefined,
      page.value,
      pageSize.value,
      currentVersion.value || undefined,
    )
    documents.value = res.items ?? []
    total.value = res.total ?? 0
  } catch {
    documents.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function loadStats(): Promise<void> {
  try {
    stats.value = await getDocumentStats(libraryName.value, currentVersion.value || undefined)
  } catch {
    stats.value = null
  }
}

async function loadLibrary(): Promise<void> {
  libraryLoading.value = true
  try {
    library.value = await getDocsMcpLibraryDetail(libraryName.value)
  } catch (e) {
    toast.error((e as Error).message || '加载文档库失败')
  } finally {
    libraryLoading.value = false
  }
}

function handleSearch(query: string): void {
  hasSearched.value = true
  activeQuery.value = query
  searchNonce.value++
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function pollDocStatus(docId: number): Promise<void> {
  // 入库走 Celery 异步，派发后轮询单文档状态直到终态
  const maxAttempts = 40
  for (let i = 0; i < maxAttempts; i++) {
    await sleep(1500)
    try {
      const d = await getDocument(docId)
      if (d.ingest_status === 'ingested' || d.ingest_status === 'failed') {
        await loadDocuments()
        await loadStats()
        if (d.ingest_status === 'ingested') {
          toast.success('入库成功')
        } else {
          toast.error(`入库失败：${d.error_message || '未知原因'}`)
        }
        return
      }
      await loadDocuments()
    } catch {
      // 单次查询失败不中断轮询
    }
  }
  await loadDocuments()
  await loadStats()
}

async function handleIngest(doc: Document): Promise<void> {
  if (ingestingId.value) return
  ingestingId.value = doc.id
  try {
    await ingestDocument(doc.id)
    toast.success('入库任务已提交')
    await pollDocStatus(doc.id)
  } catch (e) {
    toast.error((e as Error).message || '提交入库失败')
  } finally {
    ingestingId.value = null
  }
}

async function pollBatchStatus(): Promise<void> {
  const maxAttempts = 60
  for (let i = 0; i < maxAttempts; i++) {
    await sleep(1500)
    await loadStats()
    await loadDocuments()
    if ((stats.value?.by_status?.pending ?? 0) === 0) {
      return
    }
  }
}

async function handleBatchIngest(): Promise<void> {
  if (batchIngesting.value) return
  batchIngesting.value = true
  try {
    await ingestDocumentBatch({ library: libraryName.value })
    toast.success('批量入库任务已提交')
    await pollBatchStatus()
  } catch (e) {
    toast.error((e as Error).message || '提交批量入库失败')
  } finally {
    batchIngesting.value = false
  }
}

async function handleDelete(doc: Document): Promise<void> {
  if (deletingId.value) return
  deletingId.value = doc.id
  try {
    await deleteDocument(doc.id)
    toast.success('文档已删除')
    await loadDocuments()
    await loadStats()
  } catch (e) {
    toast.error((e as Error).message || '删除失败')
  } finally {
    deletingId.value = null
  }
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
    showScrapeDialog.value = false
    showAddVersionDialog.value = false
    await loadLibrary()
    await loadDocuments()
    await loadStats()
  } catch (e) {
    toast.error((e as Error).message || '创建失败')
  }
}

async function handleUploaded(): Promise<void> {
  await loadDocuments()
  await loadStats()
}

function connectSSE(): void {
  const url = getDocsMcpEventSourceUrl()
  eventSource = new EventSource(url)
  eventSource.addEventListener('job-status-change', () => {
    loadLibrary()
    loadDocuments()
    loadStats()
  })
  eventSource.addEventListener('job-progress', () => {
    loadLibrary()
    loadDocuments()
    loadStats()
  })
  eventSource.addEventListener('job-list-change', () => {
    loadLibrary()
    loadDocuments()
    loadStats()
  })
  eventSource.onerror = () => {
    if (eventSource) {
      eventSource.close()
      setTimeout(connectSSE, 5000)
    }
  }
}

// ── 库级接口总览入口 ──

function goLibraryInterfaces(): void {
  router.push({ name: 'LibraryInterfaces', params: { libraryName: libraryName.value } })
}

watch([sourceFilter, statusFilter], () => {
  page.value = 1
  loadDocuments()
})

watch(currentVersion, () => {
  page.value = 1
  loadDocuments()
  loadStats()
})

onMounted(() => {
  loadLibrary()
  loadDocuments()
  loadStats()
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
  <div class="space-y-4">
    <div class="flex items-center gap-3">
      <button
        class="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        @click="router.push({ name: 'DocsMcp' })"
      >
        <ArrowLeft class="h-4 w-4" />
      </button>
      <h2 class="text-lg font-semibold text-gray-900">{{ libraryName }}</h2>
      <select
        v-model="selectedVersion"
        :disabled="libraryLoading"
        class="rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50"
        title="切换版本"
      >
        <option v-for="o in versionOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <button
        class="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        @click="showAddVersionDialog = true"
      >
        <Plus class="h-4 w-4" />
        新增版本
      </button>
      <div class="ml-auto flex items-center gap-2">
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          @click="showScrapeDialog = true"
        >
          <Plus class="h-4 w-4" />
          爬取增量
        </button>
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
          @click="showUploadDialog = true"
        >
          <Upload class="h-4 w-4" />
          上传增量
        </button>
        <button
          class="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          @click="goLibraryInterfaces"
        >
          <Code2 class="h-4 w-4" />
          接口总览
        </button>
      </div>
    </div>

    <SearchCard @search="handleSearch" />
    <DocSummary
      v-if="hasSearched"
      :key="searchNonce"
      :library-name="libraryName"
      :version="currentVersion || undefined"
      :query="activeQuery"
    />

    <div v-if="stats" class="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <div class="rounded-lg border border-gray-200 bg-white p-3">
        <div class="flex items-center gap-2 text-xs text-gray-500">
          <BarChart3 class="h-3.5 w-3.5" />
          总文档
        </div>
        <p class="mt-1 text-xl font-bold text-gray-900">{{ stats.total_documents }}</p>
      </div>
      <div class="rounded-lg border border-gray-200 bg-white p-3">
        <div class="text-xs text-gray-500">已入库</div>
        <p class="mt-1 text-xl font-bold text-green-600">{{ stats.by_status?.ingested ?? 0 }}</p>
      </div>
      <div class="rounded-lg border border-gray-200 bg-white p-3">
        <div class="text-xs text-gray-500">待入库</div>
        <p class="mt-1 text-xl font-bold text-yellow-600">{{ stats.by_status?.pending ?? 0 }}</p>
      </div>
      <div class="rounded-lg border border-gray-200 bg-white p-3">
        <div class="text-xs text-gray-500">总分块</div>
        <p class="mt-1 text-xl font-bold text-gray-900">{{ stats.total_chunks }}</p>
      </div>
    </div>

    <div class="rounded-lg border border-gray-200 bg-white">
      <div class="flex flex-wrap items-center gap-2 border-b border-gray-200 px-4 py-3">
        <select v-model="sourceFilter" class="rounded-md border border-gray-300 px-2 py-1 text-xs">
          <option v-for="o in sourceOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <select v-model="statusFilter" class="rounded-md border border-gray-300 px-2 py-1 text-xs">
          <option v-for="o in ingestStatusOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <button
          v-if="pendingCount > 0"
          class="ml-auto flex items-center gap-1 rounded-md bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100"
          :disabled="batchIngesting"
          @click="handleBatchIngest"
        >
          <Loader2 v-if="batchIngesting" class="h-3 w-3 animate-spin" />
          <ArrowDownToLine v-else class="h-3 w-3" />
          批量入库 ({{ pendingCount }})
        </button>
        <button
          class="rounded-md p-1.5 text-gray-500 hover:bg-gray-100"
          :disabled="loading"
          @click="loadDocuments(); loadStats()"
        >
          <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': loading }" />
        </button>
      </div>

      <div v-if="loading && documents.length === 0" class="flex items-center justify-center py-12">
        <Loader2 class="h-5 w-5 animate-spin text-gray-400" />
      </div>
      <div v-else-if="documents.length === 0" class="py-12 text-center text-sm text-gray-400">暂无文档</div>

      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="border-b border-gray-200 bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
            <tr>
              <th class="px-4 py-2.5">标题</th>
              <th class="px-4 py-2.5">来源</th>
              <th class="px-4 py-2.5">入库状态</th>
              <th class="px-4 py-2.5">分块数</th>
              <th class="px-4 py-2.5">更新时间</th>
              <th class="px-4 py-2.5 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100">
            <tr v-for="doc in documents" :key="doc.id" class="hover:bg-gray-50">
              <td class="max-w-[300px] truncate px-4 py-2.5 font-medium text-gray-900">{{ doc.title }}</td>
              <td class="px-4 py-2.5">
                <span
                  :class="[
                    'rounded px-1.5 py-0.5 text-xs font-medium',
                    doc.source_type === 'crawl' ? 'bg-sky-100 text-sky-700' : 'bg-amber-100 text-amber-700',
                  ]"
                >
                  {{ doc.source_type === 'crawl' ? '爬虫' : '上传' }}
                </span>
              </td>
              <td class="px-4 py-2.5">
                <span :class="['rounded-full px-2 py-0.5 text-xs font-medium', statusConfig[doc.ingest_status]?.cls ?? 'bg-gray-100 text-gray-700']">
                  {{ statusConfig[doc.ingest_status]?.label ?? doc.ingest_status }}
                </span>
              </td>
              <td class="px-4 py-2.5 text-gray-600">{{ doc.chunk_count }}</td>
              <td class="px-4 py-2.5 text-gray-500">{{ fmtTime(doc.updated_at) }}</td>
              <td class="px-4 py-2.5">
                <div class="flex items-center justify-end gap-1">
                  <button
                    class="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-blue-600"
                    title="查看"
                    @click="router.push({ name: 'DocumentDetail', params: { libraryName, docId: doc.id } })"
                  >
                    <Eye class="h-4 w-4" />
                  </button>
                  <button
                    class="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-blue-600"
                    title="编辑"
                    @click="router.push({ name: 'DocumentDetail', params: { libraryName, docId: doc.id }, query: { edit: '1' } })"
                  >
                    <Pencil class="h-4 w-4" />
                  </button>
                  <button
                    v-if="doc.ingest_status === 'pending' || doc.ingest_status === 'failed'"
                    class="rounded-md p-1.5 text-emerald-600 hover:bg-emerald-50"
                    title="入库"
                    :disabled="ingestingId === doc.id"
                    @click="handleIngest(doc)"
                  >
                    <Loader2 v-if="ingestingId === doc.id" class="h-4 w-4 animate-spin" />
                    <ArrowDownToLine v-else class="h-4 w-4" />
                  </button>
                  <button
                    class="rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500"
                    title="删除"
                    :disabled="deletingId === doc.id"
                    @click="handleDelete(doc)"
                  >
                    <Loader2 v-if="deletingId === doc.id" class="h-4 w-4 animate-spin" />
                    <Trash2 v-else class="h-4 w-4" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="total > pageSize" class="flex items-center justify-between border-t border-gray-200 px-4 py-2">
        <span class="text-xs text-gray-500">共 {{ total }} 条</span>
        <div class="flex items-center gap-1">
          <button class="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100" :disabled="page <= 1" @click="page--; loadDocuments()">上一页</button>
          <span class="px-2 text-xs text-gray-500">{{ page }}</span>
          <button class="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100" :disabled="page * pageSize >= total" @click="page++; loadDocuments()">下一页</button>
        </div>
      </div>
    </div>

    <ScrapeJobDialog
      :visible="showAddVersionDialog"
      :default-library="libraryName"
      :lock-library="true"
      @close="showAddVersionDialog = false"
      @submit="handleSubmitJob"
    />
    <ScrapeJobDialog
      :visible="showScrapeDialog"
      :default-library="libraryName"
      :default-version="currentVersion"
      :lock-library="true"
      :lock-version="true"
      @close="showScrapeDialog = false"
      @submit="handleSubmitJob"
    />
    <UploadDialog
      :visible="showUploadDialog"
      :default-library="libraryName"
      :default-version="currentVersion"
      :lock-library="true"
      :lock-version="true"
      @close="showUploadDialog = false"
      @uploaded="handleUploaded"
    />
  </div>
</template>
