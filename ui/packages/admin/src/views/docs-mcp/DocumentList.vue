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
  deleteDocsMcpVersion,
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
  Loader2,
  RefreshCw,
  BarChart3,
  Plus,
  Upload,
  Code2,
  Trash2,
  Search,
} from 'lucide-vue-next'
import ScrapeJobDialog from './components/ScrapeJobDialog.vue'
import AddVersionDialog from './components/AddVersionDialog.vue'
import UploadDialog from './components/UploadDialog.vue'
import SearchCard from './components/SearchCard.vue'
import DocSummary from './components/DocSummary.vue'

const route = useRoute()
const router = useRouter()
const libraryName = computed(() => route.params.libraryName as string)
const currentVersion = computed(() => (route.query.version as string) || '')
// 实际查看版本：路由显式选择 > 最新（与 docs-mcp 检索默认口径一致）
const effectiveVersion = computed(() => currentVersion.value || 'latest')

const documents = ref<Document[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const stats = ref<IngestStats | null>(null)
const sourceFilter = ref<string>('')
const statusFilter = ref<string>('')
const titleFilter = ref<string>('')
const ingestingId = ref<number | null>(null)
const deletingId = ref<number | null>(null)
const deletingVersion = ref(false)
const batchIngesting = ref(false)
const showScrapeDialog = ref(false)
const showUploadDialog = ref(false)
const library = ref<DocsMcpLibrary | null>(null)
const libraryLoading = ref(false)
const activeQuery = ref('')
const searchNonce = ref(0)
const showSummaryDrawer = ref(false)
const showAddVersionDialog = ref(false)
let eventSource: EventSource | null = null

// 版本下拉：最新（持续锁定最新 semver）+ 库内全部具体版本。
// 版本号强制 X.Y.Z 后无「无版本」桶，空 ref.version 一律跳过。
const versionOptions = computed(() => {
  const options: Array<{ value: string; label: string }> = [
    { value: 'latest', label: '最新' },
  ]
  for (const v of library.value?.versions ?? []) {
    const ver = v.ref.version || ''
    if (!ver) continue
    options.push({ value: ver, label: ver })
  }
  return options
})

// 是否最后一个版本：删它 = 删整个文档库（docs-mcp 库随末版本消失）
const isLastVersion = computed(
  () => (library.value?.versions ?? []).length <= 1,
)

// 新增版本默认号：取库内最大语义版本 +1 patch（1.0.0→1.0.1→1.0.2），无可解析版本则 1.0.0
const nextVersion = computed(() => {
  let best: [number, number, number] | null = null
  for (const v of library.value?.versions ?? []) {
    const m = (v.ref.version || '').replace(/^v/i, '').match(/^(\d+)\.(\d+)\.(\d+)/)
    if (!m) continue
    const cur = [Number(m[1]), Number(m[2]), Number(m[3])] as [number, number, number]
    if (
      !best ||
      cur[0] > best[0] ||
      (cur[0] === best[0] && (cur[1] > best[1] || (cur[1] === best[1] && cur[2] > best[2])))
    ) {
      best = cur
    }
  }
  return best ? `${best[0]}.${best[1]}.${best[2] + 1}` : '1.0.0'
})

// select v-model 代理：写时 router.replace 更新 query，读时取 effectiveVersion
const selectedVersion = computed<string>({
  get: () => effectiveVersion.value,
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
      effectiveVersion.value,
      titleFilter.value || undefined,
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
    stats.value = await getDocumentStats(libraryName.value, effectiveVersion.value)
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
  showSummaryDrawer.value = true
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

async function handleDelete(doc: Document): Promise<void> {
  if (!window.confirm('确认删除该文档？将同时删除其检索向量。')) return
  if (deletingId.value) return
  deletingId.value = doc.id
  try {
    await deleteDocument(doc.id)
    toast.success('删除成功')
    await loadDocuments()
    await loadStats()
  } catch (e) {
    toast.error((e as Error).message || '删除失败')
  } finally {
    deletingId.value = null
  }
}

async function handleDeleteVersion(): Promise<void> {
  if (deletingVersion.value) return
  const ver = currentVersion.value || 'latest'
  const confirmMsg = isLastVersion.value
    ? `这是最后一个版本。删除后将移除整个文档库「${libraryName.value}」及其全部数据，且不可恢复。确定删除？`
    : `确认删除版本「${ver}」？该版本下所有文档及检索向量将被删除。`
  if (!window.confirm(confirmMsg)) return
  deletingVersion.value = true
  try {
    await deleteDocsMcpVersion(libraryName.value, ver)
    if (isLastVersion.value) {
      toast.success('文档库已删除')
      router.push({ name: 'DocsMcp' })
      return
    }
    toast.success('版本已删除')
    await loadLibrary()
    // 切回 latest：watch(currentVersion) 自动重载文档列表与统计
    await router.replace({ query: { ...route.query, version: 'latest' } })
  } catch (e) {
    toast.error((e as Error).message || '删除版本失败')
  } finally {
    deletingVersion.value = false
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
  // 上传走 Celery 异步：Document 行在后台提取/入库后才落库，
  // 完成时 docs-mcp 发 library-change（爬取发 job-* 上面已订阅），此处兜底重载。
  eventSource.addEventListener('library-change', () => {
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

let titleTimer: ReturnType<typeof setTimeout> | null = null
watch(titleFilter, () => {
  page.value = 1
  if (titleTimer) clearTimeout(titleTimer)
  titleTimer = setTimeout(() => loadDocuments(), 350)
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
        class="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50"
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
      <button
        class="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="deletingVersion || libraryLoading || !library"
        :title="isLastVersion ? '删除最后一个版本将删除整个文档库' : '删除当前版本'"
        @click="handleDeleteVersion"
      >
        <Loader2 v-if="deletingVersion" class="h-4 w-4 animate-spin" />
        <Trash2 v-else class="h-4 w-4" />
        删除版本
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
        <div class="relative">
          <Search class="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" />
          <input
            v-model="titleFilter"
            type="text"
            placeholder="按标题搜索"
            class="w-44 rounded-md border border-gray-300 py-1 pl-7 pr-2 text-xs"
          />
        </div>
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
                    @click="router.push({ name: 'DocumentDetail', params: { libraryName, docId: doc.id } })"
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
                    class="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-red-600"
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

    <AddVersionDialog
      :visible="showAddVersionDialog"
      :default-library="libraryName"
      :default-version="nextVersion"
      @close="showAddVersionDialog = false"
      @crawl-submit="handleSubmitJob"
      @uploaded="handleUploaded"
    />
    <ScrapeJobDialog
      :visible="showScrapeDialog"
      :default-library="libraryName"
      :default-version="effectiveVersion"
      :lock-library="true"
      :lock-version="true"
      @close="showScrapeDialog = false"
      @submit="handleSubmitJob"
    />
    <UploadDialog
      :visible="showUploadDialog"
      :default-library="libraryName"
      :default-version="effectiveVersion"
      :lock-library="true"
      :lock-version="true"
      @close="showUploadDialog = false"
      @uploaded="handleUploaded"
    />

    <DocSummary
      v-if="showSummaryDrawer"
      :key="searchNonce"
      :library-name="libraryName"
      :version="effectiveVersion"
      :query="activeQuery"
      @close="showSummaryDrawer = false"
    />
  </div>
</template>
