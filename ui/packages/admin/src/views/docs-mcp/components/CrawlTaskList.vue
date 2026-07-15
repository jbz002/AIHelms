<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import type { CrawlTask, CrawledPage } from '@aihelms/shared'
import { getCrawlTasks, getCrawlPages, ingestCrawlTask, deleteCrawlTask } from '@aihelms/shared'
import { DatabaseSearch, ChevronDown, ChevronRight, Loader2, Trash2, ArrowDownToLine, AlertCircle } from 'lucide-vue-next'

const emit = defineEmits<{
  refresh: []
}>()

const tasks = ref<CrawlTask[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const expandedTaskId = ref<number | null>(null)
const expandedPages = ref<CrawledPage[]>([])
const expandedPagesTotal = ref(0)
const ingestingTaskId = ref<number | null>(null)
const deletingTaskId = ref<number | null>(null)

const statusConfig: Record<string, { label: string; cls: string }> = {
  pending: { label: '等待中', cls: 'bg-gray-100 text-gray-700' },
  crawling: { label: '爬取中', cls: 'bg-blue-100 text-blue-700' },
  crawled: { label: '已爬取', cls: 'bg-emerald-100 text-emerald-700' },
  ingesting: { label: '入库中', cls: 'bg-blue-100 text-blue-700' },
  ingested: { label: '已入库', cls: 'bg-purple-100 text-purple-700' },
  failed: { label: '失败', cls: 'bg-red-100 text-red-700' },
}

async function loadTasks(): Promise<void> {
  loading.value = true
  try {
    const res = await getCrawlTasks(undefined, page.value, pageSize.value)
    tasks.value = res.items ?? []
    total.value = res.total ?? 0
  } catch {
    tasks.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function toggleExpand(task: CrawlTask): Promise<void> {
  if (expandedTaskId.value === task.id) {
    expandedTaskId.value = null
    expandedPages.value = []
    return
  }
  expandedTaskId.value = task.id
  expandedPages.value = []
  try {
    const res = await getCrawlPages(task.id, 1, 100)
    expandedPages.value = res.items ?? []
    expandedPagesTotal.value = res.total ?? 0
  } catch {
    expandedPages.value = []
    expandedPagesTotal.value = 0
  }
}

async function handleIngest(task: CrawlTask): Promise<void> {
  if (ingestingTaskId.value) return
  ingestingTaskId.value = task.id
  try {
    const res = await ingestCrawlTask(task.id)
    if (res.status === 'ingested') {
      await loadTasks()
    }
  } finally {
    ingestingTaskId.value = null
  }
}

async function handleDelete(task: CrawlTask): Promise<void> {
  if (deletingTaskId.value) return
  deletingTaskId.value = task.id
  try {
    await deleteCrawlTask(task.id)
    if (expandedTaskId.value === task.id) {
      expandedTaskId.value = null
    }
    await loadTasks()
  } finally {
    deletingTaskId.value = null
  }
}

onMounted(loadTasks)

watch(total, () => {
  if (page.value > Math.ceil(total.value / pageSize.value) && page.value > 1) {
    page.value = Math.ceil(total.value / pageSize.value)
  }
})
</script>

<template>
  <div class="rounded-lg border border-gray-200 bg-white">
    <div class="flex items-center gap-2 border-b border-gray-200 px-4 py-3">
      <DatabaseSearch class="h-4 w-4 text-gray-500" />
      <h3 class="text-sm font-medium text-gray-900">爬取任务</h3>
      <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{{ total }}</span>
      <div class="ml-auto">
        <button
          class="rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
          :disabled="loading"
          @click="loadTasks"
        >
          刷新
        </button>
      </div>
    </div>

    <div v-if="loading && tasks.length === 0" class="flex items-center justify-center py-8">
      <Loader2 class="h-5 w-5 animate-spin text-gray-400" />
    </div>

    <div v-else-if="tasks.length === 0" class="py-8 text-center text-sm text-gray-400">
      暂无爬取任务
    </div>

    <div v-else>
      <div v-for="task in tasks" :key="task.id" class="border-b border-gray-100 last:border-b-0">
        <div class="flex items-center gap-3 px-4 py-3">
          <button class="rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600" @click="toggleExpand(task)">
            <ChevronDown v-if="expandedTaskId === task.id" class="h-4 w-4" />
            <ChevronRight v-else class="h-4 w-4" />
          </button>

          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="truncate text-sm font-medium text-gray-900">{{ task.library }}</span>
              <span v-if="task.version" class="text-xs text-gray-400">{{ task.version }}</span>
            </div>
            <div class="mt-0.5 flex items-center gap-2 text-xs text-gray-500">
              <a :href="task.source_url" target="_blank" class="truncate max-w-[200px] hover:text-blue-600">{{ task.source_url }}</a>
              <span>{{ task.pages_crawled }}/{{ task.pages_total }} 页</span>
            </div>
          </div>

          <span :class="['rounded-full px-2 py-0.5 text-xs font-medium', statusConfig[task.status]?.cls ?? 'bg-gray-100 text-gray-700']">
            <Loader2 v-if="task.status === 'crawling' || task.status === 'ingesting'" class="mr-1 inline h-3 w-3 animate-spin" />
            {{ statusConfig[task.status]?.label ?? task.status }}
          </span>

          <div class="flex items-center gap-1">
            <button
              v-if="task.status === 'crawled'"
              class="rounded-md p-1.5 text-emerald-600 hover:bg-emerald-50"
              title="入库"
              :disabled="ingestingTaskId === task.id"
              @click="handleIngest(task)"
            >
              <ArrowDownToLine v-if="ingestingTaskId !== task.id" class="h-4 w-4" />
              <Loader2 v-else class="h-4 w-4 animate-spin" />
            </button>
            <button
              v-if="task.status === 'failed' || task.status === 'crawled' || task.status === 'ingested'"
              class="rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500"
              title="删除"
              :disabled="deletingTaskId === task.id"
              @click="handleDelete(task)"
            >
              <Trash2 v-if="deletingTaskId !== task.id" class="h-4 w-4" />
              <Loader2 v-else class="h-4 w-4 animate-spin" />
            </button>
          </div>
        </div>

        <!-- 展开的页面列表 -->
        <div v-if="expandedTaskId === task.id" class="border-t border-gray-100 bg-gray-50 px-4 py-2">
          <div v-if="expandedPages.length === 0" class="py-4 text-center text-xs text-gray-400">暂无页面数据</div>
          <div v-else class="space-y-1">
            <div v-for="pg in expandedPages" :key="pg.id" class="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-white">
              <span class="min-w-[20px] text-center text-xs text-gray-400">{{ pg.depth }}</span>
              <a :href="pg.url" target="_blank" class="min-w-0 flex-1 truncate text-gray-700 hover:text-blue-600">{{ pg.title || pg.url }}</a>
              <span class="shrink-0 text-xs text-gray-400">{{ pg.chunks_count }} chunks</span>
            </div>
          </div>
          <div v-if="expandedPagesTotal > 100" class="mt-2 text-center text-xs text-gray-400">
            显示前 100 页，共 {{ expandedPagesTotal }} 页
          </div>
        </div>

        <!-- 错误信息 -->
        <div v-if="task.error_message && expandedTaskId !== task.id" class="border-t border-gray-100 px-4 py-2">
          <div class="flex items-center gap-1 text-xs text-red-500">
            <AlertCircle class="h-3 w-3" />
            <span class="truncate">{{ task.error_message }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="flex items-center justify-between border-t border-gray-200 px-4 py-2">
      <span class="text-xs text-gray-500">共 {{ total }} 条</span>
      <div class="flex gap-1">
        <button
          class="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100"
          :disabled="page <= 1"
          @click="page--; loadTasks()"
        >
          上一页
        </button>
        <button
          class="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100"
          :disabled="page * pageSize >= total"
          @click="page++; loadTasks()"
        >
          下一页
        </button>
      </div>
    </div>
  </div>
</template>
