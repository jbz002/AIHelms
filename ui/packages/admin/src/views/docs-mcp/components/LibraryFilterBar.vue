<script setup lang="ts">
import { Search } from 'lucide-vue-next'

interface Props {
  query: string
  status: string
  total: number
  filteredTotal: number
}

defineProps<Props>()
const emit = defineEmits<{
  'update:query': [value: string]
  'update:status': [value: string]
}>()

const statusOptions: { value: string; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'crawl', label: '网络爬取' },
  { value: 'upload', label: '文档上传' },
  { value: 'pending', label: '未入库' },
  { value: 'ingesting', label: '入库中' },
  { value: 'ingested', label: '已入库' },
  { value: 'failed', label: '失败' },
]

function onQueryInput(e: Event): void {
  emit('update:query', (e.target as HTMLInputElement).value)
}

function onStatusChange(e: Event): void {
  emit('update:status', (e.target as HTMLSelectElement).value)
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <label class="relative block">
      <Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
      <input
        :value="query"
        type="text"
        placeholder="搜索文档库名称"
        class="h-9 w-56 rounded-md border border-gray-300 bg-white pl-9 pr-3 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        @input="onQueryInput"
      />
    </label>
    <select
      :value="status"
      class="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      @change="onStatusChange"
    >
      <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
    </select>
    <span class="text-xs text-gray-500">共 {{ filteredTotal }} / {{ total }} 个库</span>
  </div>
</template>
