<script setup lang="ts">
import type { DocsMcpLibrary } from '@aihelms/shared'
import LibraryItem from './LibraryItem.vue'

interface Props {
  libraries: DocsMcpLibrary[]
}

defineProps<Props>()
</script>

<template>
  <div>
    <div v-if="libraries.length === 0" class="rounded-lg border border-dashed border-gray-200 py-8 text-center">
      <p class="text-sm text-gray-400">暂无文档，点击"新建文档"开始</p>
    </div>
    <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      <LibraryItem
        v-for="lib in libraries"
        :key="lib.library"
        :library="lib"
      />
    </div>
  </div>
</template>
