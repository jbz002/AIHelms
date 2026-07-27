<script setup lang="ts">
import { ref } from 'vue'
import { Search, Loader2 } from 'lucide-vue-next'

interface Emits {
  search: [query: string]
}

const emit = defineEmits<Emits>()

const query = ref('')
const searching = ref(false)

function handleSearch(): void {
  if (!query.value.trim()) return
  searching.value = true
  emit('search', query.value.trim())
  setTimeout(() => {
    searching.value = false
  }, 500)
}
</script>

<template>
  <div class="rounded-lg border border-gray-200 bg-white p-4">
    <div class="flex items-end gap-3">
      <div class="flex-1">
        <label class="mb-1 block text-sm font-medium text-gray-700">搜索当前版本文档</label>
        <input
          v-model="query"
          type="text"
          placeholder="输入搜索内容..."
          class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          @keyup.enter="handleSearch"
        />
      </div>
      <button
        class="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        :disabled="!query.trim() || searching"
        @click="handleSearch"
      >
        <Loader2 v-if="searching" class="h-4 w-4 animate-spin" />
        <Search v-else class="h-4 w-4" />
        搜索
      </button>
    </div>
  </div>
</template>
