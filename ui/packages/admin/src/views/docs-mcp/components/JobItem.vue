<script setup lang="ts">
import type { DocsMcpJob } from '@aihelms/shared'
import { XCircle, Loader2 } from 'lucide-vue-next'

interface Props {
  job: DocsMcpJob
}

interface Emits {
  cancel: [jobId: string]
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

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
</script>

<template>
  <div class="rounded-lg border border-gray-200 bg-white p-4">
    <div class="flex items-start justify-between">
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
          v-if="job.status === 'queued' || job.status === 'running'"
          class="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-red-500"
          title="取消任务"
          @click="emit('cancel', job.id)"
        >
          <XCircle class="h-4 w-4" />
        </button>
      </div>
    </div>
  </div>
</template>
