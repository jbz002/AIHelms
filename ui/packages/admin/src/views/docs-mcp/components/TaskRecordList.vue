<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import type { DocTask, DocTaskSource, DocTaskStatus, CrawledPage } from '@aihelms/shared'
import {
  getDocTasks,
  getCrawlPages,
  ingestCrawlTask,
  ingestUploadRecord,
  getUploadRecordContent,
  pauseCrawlTask,
  resumeCrawlTask,
  deleteCrawlTask,
  deleteUploadRecord,
  toast,
  copyText,
} from '@aihelms/shared'
import {
  ListChecks,
  Globe,
  FileText,
  ChevronDown,
  ChevronRight,
  Loader2,
  ArrowDownToLine,
  AlertCircle,
  RefreshCw,
  Pause,
  Play,
  Copy,
  Check,
  Trash2,
} from 'lucide-vue-next'

const props = defineProps<{ libraryName?: string }>()
const emit = defineEmits<{ refresh: [] }>()

const tasks = ref<DocTask[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const sourceFilter = ref<'' | DocTaskSource>('')
const statusFilter = ref<'' | DocTaskStatus>('')
const dateFilter = ref<string>('today')
const expandedKey = ref<string | null>(null)
const expandedPages = ref<CrawledPage[]>([])
const expandedPagesTotal = ref(0)
const ingestingKey = ref<string | null>(null)
const pausingKey = ref<string | null>(null)
const resumingKey = ref<string | null>(null)
const deletingKey = ref<string | null>(null)
const contentExpandedKey = ref<string | null>(null)
const contentLoadingKey = ref<string | null>(null)
const contentCache = ref<Record<string, string>>({})
const copiedKey = ref<string | null>(null)

const pollTimer = ref<ReturnType<typeof setTimeout> | null>(null)
const IN_FLIGHT_STATUSES = new Set<DocTaskStatus>(['pending', 'processing', 'ingesting'])

function schedulePoll(): void {
  if (pollTimer.value) return
  pollTimer.value = setTimeout(async () => {
    pollTimer.value = null
    await loadTasks()
  }, 2000)
}

function stopPoll(): void {
  if (pollTimer.value) {
    clearTimeout(pollTimer.value)
    pollTimer.value = null
  }
}

const statusConfig: Record<DocTaskStatus, { label: string; cls: string; spin: boolean }> = {
  pending: { label: '等待中', cls: 'bg-gray-100 text-gray-700', spin: false },
  processing: { label: '处理中', cls: 'bg-blue-100 text-blue-700', spin: true },
  ready: { label: '待入库', cls: 'bg-emerald-100 text-emerald-700', spin: false },
  ingesting: { label: '入库中', cls: 'bg-blue-100 text-blue-700', spin: true },
  ingested: { label: '已入库', cls: 'bg-purple-100 text-purple-700', spin: false },
  failed: { label: '失败', cls: 'bg-red-100 text-red-700', spin: false },
  duplicate: { label: '重复跳过', cls: 'bg-gray-100 text-gray-500', spin: false },
  paused: { label: '已暂停', cls: 'bg-amber-100 text-amber-700', spin: false },
}

const sourceConfig: Record<DocTaskSource, { label: string; icon: typeof Globe; cls: string }> = {
  external_crawl: { label: '爬虫', icon: Globe, cls: 'bg-sky-100 text-sky-700' },
  internal_upload: { label: '上传', icon: FileText, cls: 'bg-amber-100 text-amber-700' },
}

const sourceOptions: { value: '' | DocTaskSource; label: string }[] = [
  { value: '', label: '全部来源' },
  { value: 'external_crawl', label: '外部文档(爬虫)' },
  { value: 'internal_upload', label: '内部文档(上传)' },
]

const statusOptions: { value: '' | DocTaskStatus; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '等待中' },
  { value: 'processing', label: '处理中' },
  { value: 'ready', label: '待入库' },
  { value: 'ingesting', label: '入库中' },
  { value: 'ingested', label: '已入库' },
  { value: 'failed', label: '失败' },
  { value: 'duplicate', label: '重复跳过' },
  { value: 'paused', label: '已暂停' },
]

const dateOptions: { value: string; label: string }[] = [
  { value: 'today', label: '今天' },
  { value: '7d', label: '近7天' },
  { value: '30d', label: '近30天' },
  { value: '', label: '全部' },
]

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 19)
}

function displayUrl(currentUrl: string, sourceUrl: string): string {
  if (!currentUrl || !sourceUrl) return currentUrl
  const base = sourceUrl.replace(/\/+$/, '')
  if (currentUrl.startsWith(base + '/')) {
    const rel = currentUrl.slice(base.length)
    // 剥离后只剩 "/" 或空，说明当前 URL 就是起始页，显示完整 URL 最后一段路径
    if (!rel || rel === '/') {
      try {
        return new URL(currentUrl).pathname
      } catch {
        return currentUrl
      }
    }
    return rel
  }
  // 按路径段找公共前缀
  const curParts = currentUrl.split('/')
  const srcParts = base.split('/')
  let common = 0
  for (let i = 0; i < curParts.length && i < srcParts.length; i++) {
    if (curParts[i] === srcParts[i]) common++
    else break
  }
  if (common >= 3) return '/' + curParts.slice(common).join('/')
  return currentUrl
}

function partialHint(task: DocTask): string {
  const parts: string[] = []
  if (task.pages_backfilled) parts.push(`${task.pages_backfilled} 页为 SSE 中断后从 docs-mcp 回补`)
  if (task.pages_empty) parts.push(`${task.pages_empty} 页内容为空未向量化`)
  return `部分页未完整入库：${parts.join('；')}。非爬取异常，已入库内容完整可用`
}

async function loadTasks(): Promise<void> {
  loading.value = true
  try {
    const res = await getDocTasks(
      sourceFilter.value || undefined,
      statusFilter.value || undefined,
      page.value,
      pageSize.value,
      dateFilter.value || undefined,
      props.libraryName,
    )
    tasks.value = res.items ?? []
    total.value = res.total ?? 0
  } catch {
    tasks.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
  // 有 in-flight 任务时轮询(配合后端分阶段 commit,可见 ingesting 态与入库进度);
  // 全稳态时停止。SSE 事件仍会触发 loadTasks,双通道保障。
  if (tasks.value.some((t) => IN_FLIGHT_STATUSES.has(t.status))) {
    schedulePoll()
  } else {
    stopPoll()
  }
}

async function toggleExpand(task: DocTask): Promise<void> {
  if (expandedKey.value === task.key) {
    expandedKey.value = null
    expandedPages.value = []
    return
  }
  expandedKey.value = task.key
  expandedPages.value = []
  if (task.source !== 'external_crawl') return
  try {
    const res = await getCrawlPages(task.raw_id, 1, 100)
    expandedPages.value = res.items ?? []
    expandedPagesTotal.value = res.total ?? 0
  } catch {
    expandedPages.value = []
    expandedPagesTotal.value = 0
  }
}

async function handleIngest(task: DocTask): Promise<void> {
  if (ingestingKey.value) return
  ingestingKey.value = task.key
  try {
    if (task.source === 'external_crawl') {
      await ingestCrawlTask(task.raw_id)
    } else {
      await ingestUploadRecord(task.raw_id)
    }
    toast.success('入库任务已提交，后台处理中')
    await loadTasks()
    emit('refresh')
  } catch (e) {
    toast.error((e as Error).message || '提交入库失败')
  } finally {
    ingestingKey.value = null
  }
}

async function handlePause(task: DocTask) {
  if (!task.key.startsWith('crawl-') || pausingKey.value) return
  pausingKey.value = task.key
  try {
    await pauseCrawlTask(task.raw_id)
    toast.success('任务已暂停')
  } catch (e) {
    toast.error((e as Error).message || '暂停失败')
  } finally {
    pausingKey.value = null
  }
  await loadTasks()
  emit('refresh')
}

async function handleResume(task: DocTask) {
  if (!task.key.startsWith('crawl-') || resumingKey.value) return
  resumingKey.value = task.key
  try {
    await resumeCrawlTask(task.raw_id)
    toast.success('任务已恢复')
  } catch (e) {
    toast.error((e as Error).message || '恢复失败')
  } finally {
    resumingKey.value = null
  }
  await loadTasks()
  emit('refresh')
}

async function handleDelete(task: DocTask): Promise<void> {
  if (deletingKey.value) return
  deletingKey.value = task.key
  try {
    if (task.source === 'external_crawl') {
      await deleteCrawlTask(task.raw_id)
    } else {
      await deleteUploadRecord(task.raw_id)
    }
    toast.success('删除成功')
    await loadTasks()
    emit('refresh')
  } catch (e) {
    toast.error((e as Error).message || '删除失败')
  } finally {
    deletingKey.value = null
  }
}

async function ensureFullContent(task: DocTask): Promise<string> {
  if (contentCache.value[task.key]) return contentCache.value[task.key]
  contentLoadingKey.value = task.key
  try {
    const res = await getUploadRecordContent(task.raw_id)
    contentCache.value[task.key] = res.content
    return res.content
  } finally {
    contentLoadingKey.value = null
  }
}

async function toggleViewAll(task: DocTask): Promise<void> {
  if (contentExpandedKey.value === task.key) {
    contentExpandedKey.value = null
    return
  }
  contentExpandedKey.value = task.key
  if (!contentCache.value[task.key]) {
    try {
      await ensureFullContent(task)
    } catch (e) {
      toast.error((e as Error).message || '加载内容失败')
      contentExpandedKey.value = null
    }
  }
}

async function handleCopyContent(task: DocTask): Promise<void> {
  if (copiedKey.value === task.key) return
  try {
    const content = await ensureFullContent(task)
    if (!content) {
      toast.error('暂无可复制的内容')
      return
    }
    await copyText(content)
    copiedKey.value = task.key
    toast.success('已复制全部内容')
    setTimeout(() => {
      if (copiedKey.value === task.key) copiedKey.value = null
    }, 2000)
  } catch (e) {
    toast.error((e as Error).message || '复制失败')
  }
}

watch([sourceFilter, statusFilter, dateFilter], () => {
  page.value = 1
  stopPoll()
  loadTasks()
})

onMounted(loadTasks)

onUnmounted(stopPoll)

defineExpose({ loadTasks })
</script>

<template>
  <div class="rounded-lg border border-gray-200 bg-white">
    <div class="flex flex-wrap items-center gap-2 border-b border-gray-200 px-4 py-3">
      <ListChecks class="h-4 w-4 text-gray-500" />
      <h3 class="text-sm font-medium text-gray-900">文档任务</h3>
      <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{{ total }}</span>
      <select v-model="sourceFilter" class="ml-auto rounded-md border border-gray-300 px-2 py-1 text-xs">
        <option v-for="o in sourceOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <select v-model="statusFilter" class="rounded-md border border-gray-300 px-2 py-1 text-xs">
        <option v-for="o in statusOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <select v-model="dateFilter" class="rounded-md border border-gray-300 px-2 py-1 text-xs">
        <option v-for="o in dateOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <button class="rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700" :disabled="loading" @click="loadTasks">
        <RefreshCw class="h-3 w-3" :class="{ 'animate-spin': loading }" />
      </button>
    </div>

    <div v-if="loading && tasks.length === 0" class="flex items-center justify-center py-8">
      <Loader2 class="h-5 w-5 animate-spin text-gray-400" />
    </div>
    <div v-else-if="tasks.length === 0" class="py-8 text-center text-sm text-gray-400">暂无文档任务</div>

    <div v-else>
      <div v-for="task in tasks" :key="task.key" class="border-b border-gray-100 last:border-b-0">
        <div class="flex items-center gap-3 px-4 py-3">
          <button class="rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600" @click="toggleExpand(task)">
            <ChevronDown v-if="expandedKey === task.key" class="h-4 w-4" />
            <ChevronRight v-else class="h-4 w-4" />
          </button>
          <component :is="(sourceConfig[task.source] ?? sourceConfig.internal_upload).icon" class="h-4 w-4 shrink-0 text-gray-400" />
          <span :class="['shrink-0 rounded px-1.5 py-0.5 text-xs font-medium', (sourceConfig[task.source] ?? sourceConfig.internal_upload).cls]">{{ (sourceConfig[task.source] ?? sourceConfig.internal_upload).label }}</span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="truncate text-sm font-medium text-gray-900">{{ task.title }}</span>
              <span v-if="task.version" class="text-xs text-gray-400">{{ task.version }}</span>
            </div>
            <div class="mt-0.5 flex items-center gap-2 text-xs text-gray-500">
              <a v-if="task.source === 'external_crawl'" :href="task.subtitle" target="_blank" class="truncate max-w-[220px] hover:text-blue-600">{{ task.subtitle }}</a>
              <span v-else class="truncate">{{ task.subtitle }}</span>
              <span v-if="task.progress_text">{{ task.progress_text }}</span>
            </div>
            <div v-if="task.source === 'external_crawl' && task.status === 'processing' && task.current_url" class="mt-0.5 flex items-center gap-1.5 text-xs text-blue-600">
              <span class="relative flex h-2 w-2">
                <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
                <span class="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
              </span>
              <a :href="task.current_url" target="_blank" class="truncate max-w-[280px] hover:text-blue-800">{{ displayUrl(task.current_url, task.subtitle) }}</a>
            </div>
            <div v-if="task.error_message" class="mt-0.5 flex items-center gap-1 text-xs text-red-500">
              <AlertCircle class="h-3 w-3 shrink-0" />
              <span class="truncate max-w-[340px]" :title="task.error_message">{{ task.error_message }}</span>
            </div>
          </div>
          <span :class="['shrink-0 rounded-full px-2 py-0.5 text-xs font-medium', (statusConfig[task.status] ?? statusConfig.failed).cls]">
            <Loader2 v-if="(statusConfig[task.status] ?? statusConfig.failed).spin" class="mr-1 inline h-3 w-3 animate-spin" />
            {{ (statusConfig[task.status] ?? statusConfig.failed).label }}
          </span>
          <span v-if="task.is_partial" class="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700" :title="partialHint(task)">
            <AlertCircle class="h-3 w-3" />
            部分页未入库
          </span>
          <div class="flex shrink-0 items-center">
            <button
              v-if="task.source === 'external_crawl' && (task.status === 'processing' || task.status === 'ingesting')"
              class="rounded-md p-1 text-gray-400 hover:bg-amber-50 hover:text-amber-500"
              title="暂停"
              :disabled="pausingKey === task.key"
              @click="handlePause(task)"
            >
              <Loader2 v-if="pausingKey === task.key" class="h-4 w-4 animate-spin" />
              <Pause v-else class="h-4 w-4" />
            </button>
            <button
              v-if="task.source === 'external_crawl' && (task.status === 'paused' || task.status === 'failed')"
              class="rounded-md p-1 text-emerald-600 hover:bg-emerald-50"
              :title="task.status === 'failed' ? '续爬（跳过已爬页）' : '恢复'"
              :disabled="resumingKey === task.key"
              @click="handleResume(task)"
            >
              <Loader2 v-if="resumingKey === task.key" class="h-4 w-4 animate-spin" />
              <Play v-else class="h-4 w-4" />
            </button>
            <button v-if="task.can_ingest" class="rounded-md p-1 text-emerald-600 hover:bg-emerald-50" title="入库" :disabled="ingestingKey === task.key" @click="handleIngest(task)">
              <Loader2 v-if="ingestingKey === task.key" class="h-4 w-4 animate-spin" />
              <ArrowDownToLine v-else class="h-4 w-4" />
            </button>
            <button
              class="rounded-md p-1 text-gray-400 hover:bg-red-50 hover:text-red-500"
              title="删除"
              :disabled="deletingKey === task.key"
              @click="handleDelete(task)"
            >
              <Loader2 v-if="deletingKey === task.key" class="h-4 w-4 animate-spin" />
              <Trash2 v-else class="h-4 w-4" />
            </button>
          </div>
        </div>

        <div v-if="expandedKey === task.key" class="border-t border-gray-100 bg-gray-50 px-4 py-2">
          <template v-if="task.source === 'external_crawl'">
            <div v-if="expandedPages.length === 0" class="py-3 text-center text-xs text-gray-400">暂无页面数据</div>
            <div v-else class="space-y-1">
              <div v-for="pg in expandedPages" :key="pg.id" class="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-white">
                <span class="min-w-[20px] text-center text-xs text-gray-400">{{ pg.depth }}</span>
                <a :href="pg.url" target="_blank" class="min-w-0 flex-1 truncate text-gray-700 hover:text-blue-600">{{ pg.title || pg.url }}</a>
                <span class="shrink-0 text-xs text-gray-400">{{ pg.chunks_count }} chunks</span>
              </div>
            </div>
            <div v-if="expandedPagesTotal > 100" class="mt-2 text-center text-xs text-gray-400">显示前 100 页，共 {{ expandedPagesTotal }} 页</div>
          </template>
          <template v-else>
            <div class="grid grid-cols-2 gap-2 text-xs text-gray-500">
              <div>创建：{{ fmtTime(task.created_at) }}</div>
              <div>完成：{{ fmtTime(task.finished_at) || '-' }}</div>
            </div>
            <div v-if="task.extracted_content_preview" class="mt-2 rounded-md bg-white p-2">
              <div class="mb-1 flex items-center justify-between">
                <p class="text-xs text-gray-400">提取内容预览</p>
                <div class="flex items-center gap-1">
                  <button
                    class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50"
                    :disabled="contentLoadingKey === task.key"
                    @click="toggleViewAll(task)"
                  >
                    <Loader2 v-if="contentLoadingKey === task.key" class="h-3 w-3 animate-spin" />
                    <template v-else>{{ contentExpandedKey === task.key ? '收起' : '查看全部' }}</template>
                  </button>
                  <button
                    class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50"
                    :disabled="contentLoadingKey === task.key"
                    @click="handleCopyContent(task)"
                  >
                    <Check v-if="copiedKey === task.key" class="h-3 w-3 text-emerald-500" />
                    <Copy v-else class="h-3 w-3" />
                    {{ copiedKey === task.key ? '已复制' : '复制内容' }}
                  </button>
                </div>
              </div>
              <pre :class="['overflow-auto text-xs leading-relaxed text-gray-700 whitespace-pre-wrap break-words', contentExpandedKey === task.key ? 'max-h-[60vh]' : 'max-h-32']">{{ contentExpandedKey === task.key ? (contentCache[task.key] ?? task.extracted_content_preview) : task.extracted_content_preview }}</pre>
            </div>
          </template>
          <div v-if="task.error_message" class="mt-2 flex items-center gap-1 text-xs text-red-500">
            <AlertCircle class="h-3 w-3" />
            <span>{{ task.error_message }}</span>
          </div>
        </div>
      </div>

      <div v-if="total > pageSize" class="flex items-center justify-between border-t border-gray-200 px-4 py-2">
        <span class="text-xs text-gray-500">共 {{ total }} 条</span>
        <div class="flex items-center gap-1">
          <button class="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100" :disabled="page <= 1" @click="page--; loadTasks()">上一页</button>
          <span class="px-2 text-xs text-gray-500">{{ page }}</span>
          <button class="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100" :disabled="page * pageSize >= total" @click="page++; loadTasks()">下一页</button>
        </div>
      </div>
    </div>
  </div>
</template>
