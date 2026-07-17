<script setup lang="ts">
import { ref } from 'vue'
import type { DocsMcpVersion } from '@aihelms/shared'
import { Trash2, Eraser } from 'lucide-vue-next'

interface Props {
  version: DocsMcpVersion
  libraryName: string
  isLastVersion?: boolean
}

interface Emits {
  delete: [library: string, version: string]
  clearDocuments: [library: string, version: string]
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const showDeleteConfirm = ref(false)
const showClearConfirm = ref(false)

const statusColor: Record<string, string> = {
  completed: 'bg-emerald-100 text-emerald-700',
  running: 'bg-blue-100 text-blue-700',
  queued: 'bg-yellow-100 text-yellow-700',
  failed: 'bg-red-100 text-red-700',
  cancelled: 'bg-gray-100 text-gray-700',
  updating: 'bg-blue-100 text-blue-700',
  not_indexed: 'bg-gray-100 text-gray-600',
}

function handleDelete(): void {
  emit('delete', props.libraryName, props.version.ref.version)
}

function handleClearDocuments(): void {
  emit('clearDocuments', props.libraryName, props.version.ref.version)
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
        v-if="version.counts?.documents ?? 0 > 0"
        class="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-orange-500"
        title="清除文档（保留版本记录，可重新抓取）"
        @click="showClearConfirm = true"
      >
        <Eraser class="h-3.5 w-3.5" />
      </button>
      <button
        v-if="!showDeleteConfirm && !showClearConfirm"
        class="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-red-500"
        :title="isLastVersion ? '删除版本（最后一个版本，将移除整个文档库）' : '删除版本'"
        @click="showDeleteConfirm = true"
      >
        <Trash2 class="h-3.5 w-3.5" />
      </button>
      <!-- Clear documents confirm -->
      <template v-if="showClearConfirm">
        <button
          class="rounded-md bg-orange-500 px-2 py-1 text-xs font-medium text-white hover:bg-orange-600"
          @click="handleClearDocuments"
        >
          清除文档
        </button>
        <button
          class="rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100"
          @click="showClearConfirm = false"
        >
          取消
        </button>
      </template>
      <!-- Delete confirm -->
      <template v-if="showDeleteConfirm && !showClearConfirm">
        <span v-if="isLastVersion" class="text-xs font-medium text-red-600">
          最后一个版本，删除将移除整个文档库
        </span>
        <button
          class="rounded-md bg-red-500 px-2 py-1 text-xs font-medium text-white hover:bg-red-600"
          @click="handleDelete"
        >
          {{ isLastVersion ? '确认删除文档库' : '确认删除' }}
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
