<script setup lang="ts">
import { useRouter } from 'vue-router'
import type { DocsMcpLibrary } from '@aihelms/shared'
import { ExternalLink } from 'lucide-vue-next'

interface Props {
  library: DocsMcpLibrary
}

const props = defineProps<Props>()
const router = useRouter()

function goToDetail(): void {
  router.push({
    name: 'DocumentList',
    params: { libraryName: props.library.library },
    query: { version: 'latest' },
  })
}
</script>

<template>
  <div
    class="cursor-pointer rounded-lg border border-gray-200 bg-white p-4 transition-colors hover:border-blue-200 hover:bg-blue-50/30"
    @click="goToDetail"
  >
    <div class="flex items-start justify-between">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <h4 class="truncate text-sm font-medium text-gray-900">{{ library.library }}</h4>
          <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
            {{ library.versions.length }} 个版本
          </span>
        </div>
        <div v-if="library.versions.length > 0 && library.versions[0].sourceUrl" class="mt-1 truncate text-xs text-gray-400">
          {{ library.versions[0].sourceUrl }}
        </div>
        <div class="mt-2 flex flex-wrap gap-2">
          <span
            v-for="ver in library.versions.slice(0, 3)"
            :key="ver.ref.version || '_default'"
            class="inline-flex items-center rounded-full px-2 py-0.5 text-xs"
            :class="{
              'bg-emerald-100 text-emerald-700': ver.status === 'completed',
              'bg-blue-100 text-blue-700': ver.status === 'running' || ver.status === 'queued' || ver.status === 'updating',
              'bg-red-100 text-red-700': ver.status === 'failed',
              'bg-gray-100 text-gray-600': ver.status === 'cancelled' || ver.status === 'not_indexed',
            }"
          >
            {{ ver.ref.version || '默认' }}
            <span class="ml-1 text-[10px] opacity-70">
              {{ ver.counts?.uniqueUrls ?? 0 }}页
            </span>
          </span>
        </div>
      </div>
      <ExternalLink class="mt-1 h-4 w-4 shrink-0 text-gray-300" />
    </div>
  </div>
</template>
