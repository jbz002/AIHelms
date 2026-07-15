<script setup lang="ts">
import { ref } from 'vue'
import type { DocsMcpJob, DocsMcpScrapeOptions } from '@aihelms/shared'
import { getDocsMcpJobDetail } from '@aihelms/shared'
import { XCircle, ChevronDown, ChevronUp, Clock, Globe, Settings, Loader2 } from 'lucide-vue-next'

interface Props {
  job: DocsMcpJob
}

interface Emits {
  cancel: [jobId: string]
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const expanded = ref(false)
const detailLoading = ref(false)
const detail = ref<DocsMcpJob | null>(null)

const statusColor: Record<string, string> = {
  completed: 'bg-emerald-100 text-emerald-700',
  running: 'bg-blue-100 text-blue-700',
  queued: 'bg-yellow-100 text-yellow-700',
  failed: 'bg-red-100 text-red-700',
  cancelling: 'bg-orange-100 text-orange-700',
  cancelled: 'bg-gray-100 text-gray-700',
}

const progressPercent = () => {
  const p = props.job.progress
  if (!p || p.totalPages <= 0) return 0
  return Math.round((p.pagesScraped / p.totalPages) * 100)
}

async function toggleDetail(): Promise<void> {
  if (expanded.value) {
    expanded.value = false
    return
  }
  expanded.value = true
  detailLoading.value = true
  try {
    detail.value = await getDocsMcpJobDetail(props.job.id)
  } catch {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString()
}
</script>

<template>
  <div class="rounded-lg border border-gray-200 bg-white">
    <div class="flex items-start justify-between p-4">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="truncate text-sm font-medium text-gray-900">{{ job.library }}</span>
          <span
            v-if="job.version"
            class="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600"
          >
            {{ job.version }}
          </span>
          <span :class="['rounded-full px-2 py-0.5 text-xs font-medium', statusColor[job.status] ?? 'bg-gray-100 text-gray-600']">
            {{ job.status }}
          </span>
        </div>
        <div v-if="job.sourceUrl" class="mt-1 truncate text-xs text-gray-400">
          {{ job.sourceUrl }}
        </div>
        <!-- Progress bar -->
        <div v-if="job.status === 'running' && job.progress" class="mt-2">
          <div class="h-2 w-full overflow-hidden rounded-full bg-gray-100">
            <div
              class="h-full rounded-full bg-blue-500 transition-all duration-300"
              :style="{ width: `${progressPercent()}%` }"
            />
          </div>
          <p class="mt-1 text-xs text-gray-500">
            {{ job.progress.pagesScraped }} / {{ job.progress.totalPages }} 页
            ({{ progressPercent() }}%)
          </p>
        </div>
        <div v-if="job.error" class="mt-1 text-xs text-red-500">
          {{ job.error.message }}
        </div>
      </div>
      <div class="ml-3 flex shrink-0 items-center gap-2">
        <span v-if="job.startedAt" class="text-xs text-gray-400">
          {{ new Date(job.startedAt).toLocaleString() }}
        </span>
        <button
          class="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          title="查看详情"
          @click="toggleDetail"
        >
          <ChevronUp v-if="expanded" class="h-4 w-4" />
          <ChevronDown v-else class="h-4 w-4" />
        </button>
        <button
          v-if="job.status === 'queued' || job.status === 'running'"
          class="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-red-500"
          title="取消任务"
          @click="emit('cancel', job.id)"
        >
          <XCircle class="h-4 w-4" />
        </button>
      </div>
    </div>

    <!-- Expandable detail panel -->
    <div v-if="expanded" class="border-t border-gray-100 bg-gray-50/50 px-4 py-3">
      <Loader2 v-if="detailLoading" class="mx-auto h-5 w-5 animate-spin text-gray-300" />
      <div v-else-if="detail" class="space-y-3 text-xs">
        <!-- Timeline -->
        <div class="flex items-center gap-4 text-gray-500">
          <span class="inline-flex items-center gap-1">
            <Clock class="h-3 w-3" />
            创建: {{ formatTime(detail.createdAt) }}
          </span>
          <span class="inline-flex items-center gap-1">
            开始: {{ formatTime(detail.startedAt) }}
          </span>
          <span class="inline-flex items-center gap-1">
            完成: {{ formatTime(detail.finishedAt) }}
          </span>
        </div>

        <!-- Scraper options -->
        <div v-if="detail.scraperOptions">
          <div class="mb-1 inline-flex items-center gap-1 font-medium text-gray-600">
            <Settings class="h-3 w-3" />
            抓取配置
          </div>
          <div class="flex flex-wrap gap-2">
            <span v-if="detail.scraperOptions.maxPages" class="rounded bg-white px-1.5 py-0.5 border border-gray-200">
              最大页数: {{ detail.scraperOptions.maxPages }}
            </span>
            <span v-if="detail.scraperOptions.maxDepth" class="rounded bg-white px-1.5 py-0.5 border border-gray-200">
              最大深度: {{ detail.scraperOptions.maxDepth }}
            </span>
            <span v-if="detail.scraperOptions.scope" class="rounded bg-white px-1.5 py-0.5 border border-gray-200">
              范围: {{ detail.scraperOptions.scope }}
            </span>
            <span v-if="detail.scraperOptions.scrapeMode" class="rounded bg-white px-1.5 py-0.5 border border-gray-200">
              模式: {{ detail.scraperOptions.scrapeMode }}
            </span>
          </div>
        </div>

        <!-- Source URL -->
        <div v-if="detail.sourceUrl" class="inline-flex items-center gap-1 text-gray-500">
          <Globe class="h-3 w-3" />
          <span class="break-all">{{ detail.sourceUrl }}</span>
        </div>

        <!-- Full error message -->
        <div v-if="detail.errorMessage" class="rounded bg-red-50 px-2 py-1 text-red-600">
          {{ detail.errorMessage }}
        </div>
      </div>
      <div v-else class="text-xs text-gray-400">
        无法加载详情
      </div>
    </div>
  </div>
</template>
