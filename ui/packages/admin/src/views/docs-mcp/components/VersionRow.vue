<script setup lang="ts">
import { ref } from 'vue'
import type { DocsMcpVersion } from '@aihelms/shared'
import { RefreshCw, Trash2, Loader2 } from 'lucide-vue-next'

interface Props {
  version: DocsMcpVersion
  libraryName: string
}

interface Emits {
  refresh: [library: string, version: string, versionId: number]
  delete: [library: string, version: string]
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const refreshing = ref(false)
const showDeleteConfirm = ref(false)

const statusColor: Record<string, string> = {
  completed: 'bg-emerald-100 text-emerald-700',
  running: 'bg-blue-100 text-blue-700',
  queued: 'bg-yellow-100 text-yellow-700',
  failed: 'bg-red-100 text-red-700',
  cancelled: 'bg-gray-100 text-gray-700',
  updating: 'bg-blue-100 text-blue-700',
  not_indexed: 'bg-gray-100 text-gray-600',
}

async function handleRefresh(): Promise<void> {
  refreshing.value = true
  emit('refresh', props.libraryName, props.version.ref.version, props.version.id)
  setTimeout(() => {
    refreshing.value = false
  }, 1000)
}

function handleDelete(): void {
  emit('delete', props.libraryName, props.version.ref.version)
}
</script>

<template>
  <div class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2">
    <div class="flex items-center gap-3">
      <span :class="['rounded-full px-2 py-0.5 text-xs font-medium', statusColor[version.status] ?? 'bg-gray-100 text-gray-600']">
        {{ version.ref.version || '默认' }}
      </span>
      <div class="text-xs text-gray-500">
        <span>{{ version.counts?.uniqueUrls ?? 0 }} 页</span>
        <span class="mx-1 text-gray-300">|</span>
        <span>{{ version.counts?.documents ?? 0 }} chunks</span>
        <span v-if="version.indexedAt" class="ml-1 text-gray-400">
          · {{ new Date(version.indexedAt).toLocaleDateString() }}
        </span>
      </div>
      <!-- Progress bar for running versions -->
      <div v-if="(version.status === 'running' || version.status === 'queued' || version.status === 'updating') && version.progress" class="flex items-center gap-2">
        <div class="h-1.5 w-24 overflow-hidden rounded-full bg-gray-100">
          <div
            class="h-full rounded-full bg-blue-500 transition-all duration-300"
            :style="{ width: version.progress.maxPages > 0 ? `${Math.round((version.progress.pages / version.progress.maxPages) * 100)}%` : '0%' }"
          />
        </div>
        <span class="text-xs text-gray-400">
          {{ version.progress.pages }}/{{ version.progress.maxPages }}
        </span>
      </div>
    </div>
    <div class="flex items-center gap-1">
      <button
        class="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600"
        title="刷新版本"
        :disabled="refreshing"
        @click="handleRefresh"
      >
        <Loader2 v-if="refreshing" class="h-3.5 w-3.5 animate-spin" />
        <RefreshCw v-else class="h-3.5 w-3.5" />
      </button>
      <button
        v-if="!showDeleteConfirm"
        class="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-red-500"
        title="删除版本"
        @click="showDeleteConfirm = true"
      >
        <Trash2 class="h-3.5 w-3.5" />
      </button>
      <template v-else>
        <button
          class="rounded-md bg-red-500 px-2 py-1 text-xs font-medium text-white hover:bg-red-600"
          @click="handleDelete"
        >
          确认
        </button>
        <button
          class="rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100"
          @click="showDeleteConfirm = false"
        >
          取消
        </button>
      </template>
    </div>
  </div>
</template>
