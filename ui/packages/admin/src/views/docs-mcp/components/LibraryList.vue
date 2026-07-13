<script setup lang="ts">
import type { DocsMcpLibrary } from '@aihelms/shared'
import { Plus } from 'lucide-vue-next'
import LibraryItem from './LibraryItem.vue'

interface Props {
  libraries: DocsMcpLibrary[]
}

interface Emits {
  addJob: []
}

defineProps<Props>()
defineEmits<Emits>()
</script>

<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h3 class="text-sm font-semibold text-gray-700">已索引文档</h3>
      <button
        class="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
        @click="$emit('addJob')"
      >
        <Plus class="h-3 w-3" />
        新建文档
      </button>
    </div>
    <div v-if="libraries.length === 0" class="rounded-lg border border-dashed border-gray-200 py-8 text-center">
      <p class="text-sm text-gray-400">暂无文档，点击"新建文档"开始</p>
    </div>
    <div v-else class="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <LibraryItem
        v-for="lib in libraries"
        :key="lib.library"
        :library="lib"
      />
    </div>
  </div>
</template>
