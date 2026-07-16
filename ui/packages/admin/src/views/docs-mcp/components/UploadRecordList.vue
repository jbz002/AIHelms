<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import type { DocUploadRecord } from '@aihelms/shared'
import { getDocUploadRecords, ingestUploadRecord } from '@aihelms/shared'
import { FileText, ChevronDown, ChevronRight, Loader2, ArrowDownToLine, AlertCircle, RefreshCw } from 'lucide-vue-next'

const emit = defineEmits<{ refresh: [] }>()

const records = ref<DocUploadRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const expandedId = ref<number | null>(null)
const ingestingId = ref<number | null>(null)

const statusConfig: Record<string, { label: string; cls: string }> = {
  pending: { label: '等待中', cls: 'bg-gray-100 text-gray-700' },
  extracting: { label: '提取中', cls: 'bg-blue-100 text-blue-700' },
  extracted: { label: '已提取', cls: 'bg-emerald-100 text-emerald-700' },
  ingesting: { label: '入库中', cls: 'bg-blue-100 text-blue-700' },
  completed: { label: '已入库', cls: 'bg-purple-100 text-purple-700' },
  failed: { label: '失败', cls: 'bg-red-100 text-red-700' },
}

async function loadRecords(): Promise<void> {
  loading.value = true
  try {
    const res = await getDocUploadRecords(undefined, page.value, pageSize.value)
    records.value = res.items ?? []
    total.value = res.total ?? 0
  } catch {
    records.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleToggle(record: DocUploadRecord): void {
  if (expandedId.value === record.id) {
    expandedId.value = null
  } else {
    expandedId.value = record.id
  }
}

async function handleIngest(record: DocUploadRecord): Promise<void> {
  if (ingestingId.value) return
  ingestingId.value = record.id
  try {
    const res = await ingestUploadRecord(record.id)
    if (res.status === 'completed') {
      await loadRecords()
      emit('refresh')
    }
  } finally {
    ingestingId.value = null
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

onMounted(loadRecords)

watch(total, () => {
  if (page.value > Math.ceil(total.value / pageSize.value) && page.value > 1) {
    page.value = Math.ceil(total.value / pageSize.value)
  }
})

defineExpose({ loadRecords })
</script>

<template>
  <div class="rounded-lg border border-gray-200 bg-white">
    <div class="flex items-center gap-2 border-b border-gray-200 px-4 py-3">
      <FileText class="h-4 w-4 text-gray-500" />
      <h3 class="text-sm font-medium text-gray-900">上传记录</h3>
      <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{{ total }}</span>
      <div class="ml-auto">
        <button
          class="rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
          :disabled="loading"
          @click="loadRecords"
        >
          <RefreshCw class="h-3 w-3" :class="{ 'animate-spin': loading }" />
        </button>
      </div>
    </div>

    <div v-if="loading && records.length === 0" class="flex items-center justify-center py-8">
      <Loader2 class="h-5 w-5 animate-spin text-gray-400" />
    </div>
    <div v-else-if="records.length === 0" class="py-8 text-center text-sm text-gray-400">
      暂无上传记录
    </div>
    <div v-else>
      <div v-for="record in records" :key="record.id" class="border-b border-gray-100 last:border-b-0">
        <div class="flex items-center gap-3 px-4 py-3">
          <button class="rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600" @click="handleToggle(record)">
            <ChevronDown v-if="expandedId === record.id" class="h-4 w-4" />
            <ChevronRight v-else class="h-4 w-4" />
          </button>

          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="truncate text-sm font-medium text-gray-900">{{ record.file_name }}</span>
              <span class="text-xs text-gray-400">{{ formatFileSize(record.file_size) }}</span>
            </div>
            <div class="mt-0.5 flex items-center gap-2 text-xs text-gray-500">
              <span>{{ record.library }}</span>
              <span v-if="record.version">{{ record.version }}</span>
            </div>
          </div>

          <span :class="['rounded-full px-2 py-0.5 text-xs font-medium', statusConfig[record.status]?.cls ?? 'bg-gray-100 text-gray-700']">
            <Loader2 v-if="record.status === 'extracting' || record.status === 'ingesting'" class="mr-1 inline h-3 w-3 animate-spin" />
            {{ statusConfig[record.status]?.label ?? record.status }}
          </span>

          <div class="flex items-center gap-1">
            <button
              v-if="record.status === 'extracted'"
              class="rounded-md p-1.5 text-emerald-600 hover:bg-emerald-50"
              title="入库"
              :disabled="ingestingId === record.id"
              @click="handleIngest(record)"
            >
              <ArrowDownToLine v-if="ingestingId !== record.id" class="h-4 w-4" />
              <Loader2 v-else class="h-4 w-4 animate-spin" />
            </button>
          </div>
        </div>

        <!-- 展开的详情 -->
        <div v-if="expandedId === record.id" class="border-t border-gray-100 bg-gray-50 px-4 py-2">
          <div class="grid grid-cols-2 gap-2 text-xs text-gray-500">
            <div>类型：{{ record.content_type }}</div>
            <div>块数：{{ record.chunk_count }}</div>
            <div class="col-span-2">
              创建时间：{{ record.created_at }}
            </div>
            <div v-if="record.finished_at" class="col-span-2">
              完成时间：{{ record.finished_at }}
            </div>
          </div>
          <div v-if="record.extracted_content_preview" class="mt-2 rounded-md bg-white p-2">
            <p class="text-xs text-gray-400 mb-1">提取内容预览</p>
            <pre class="max-h-32 overflow-auto text-xs leading-relaxed text-gray-700 whitespace-pre-wrap break-words">{{ record.extracted_content_preview }}...</pre>
          </div>
          <div v-if="record.error_message" class="mt-2 flex items-center gap-1 text-xs text-red-500">
            <AlertCircle class="h-3 w-3" />
            <span>{{ record.error_message }}</span>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="total > pageSize" class="flex items-center justify-between border-t border-gray-200 px-4 py-2">
        <span class="text-xs text-gray-500">共 {{ total }} 条</span>
        <div class="flex items-center gap-1">
          <button
            class="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100"
            :disabled="page <= 1"
            @click="page--; loadRecords()"
          >
            上一页
          </button>
          <span class="px-2 text-xs text-gray-500">{{ page }}</span>
          <button
            class="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100"
            :disabled="page * pageSize >= total"
            @click="page++; loadRecords()"
          >
            下一页
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
