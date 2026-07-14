<script setup lang="ts">
import { ref } from 'vue'
import type { DocsMcpSearchResult } from '@aihelms/shared'
import { MarkdownRenderer } from '@aihelms/shared'
import { FileText, ExternalLink, ChevronDown, ChevronUp } from 'lucide-vue-next'

interface Props {
  results: DocsMcpSearchResult[]
  loading?: boolean
}

defineProps<Props>()

const expandedSet = ref<Set<number>>(new Set())

function toggleExpand(index: number): void {
  const next = new Set(expandedSet.value)
  if (next.has(index)) {
    next.delete(index)
  } else {
    next.add(index)
  }
  expandedSet.value = next
}

function isExpanded(index: number): boolean {
  return expandedSet.value.has(index)
}
</script>

<template>
  <div class="mt-4">
    <h3 class="mb-3 text-sm font-semibold text-gray-700">
      搜索结果
      <span v-if="results.length > 0" class="font-normal text-gray-400">
        ({{ results.length }})
      </span>
    </h3>

    <div v-if="loading" class="space-y-3">
      <div v-for="i in 3" :key="i" class="animate-pulse rounded-lg border border-gray-100 p-4">
        <div class="h-4 w-3/4 rounded bg-gray-200" />
        <div class="mt-2 h-3 w-full rounded bg-gray-100" />
        <div class="mt-1 h-3 w-1/2 rounded bg-gray-100" />
      </div>
    </div>

    <div v-else-if="results.length === 0" class="rounded-lg border border-dashed border-gray-200 py-6 text-center">
      <p class="text-sm text-gray-400">未找到匹配结果</p>
    </div>

    <div v-else class="space-y-3">
      <div
        v-for="(result, index) in results"
        :key="index"
        class="rounded-lg border border-gray-200 bg-white p-4"
      >
        <div class="mb-2 flex items-center gap-2">
          <FileText class="h-4 w-4 shrink-0 text-gray-400" />
          <a
            :href="result.url"
            target="_blank"
            rel="noopener noreferrer"
            class="truncate text-sm font-medium text-blue-600 hover:text-blue-700"
          >
            {{ result.url }}
          </a>
          <ExternalLink class="h-3 w-3 shrink-0 text-gray-300" />
          <span v-if="result.score != null" class="ml-auto shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
            {{ (result.score * 100).toFixed(1) }}%
          </span>
        </div>

        <div v-if="isExpanded(index)">
          <MarkdownRenderer
            :content="result.content"
            :mime-type="result.mimeType"
          />
        </div>
        <div v-else class="line-clamp-4">
          <MarkdownRenderer
            :content="result.content"
            :mime-type="result.mimeType"
          />
        </div>

        <button
          class="mt-2 inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700"
          @click="toggleExpand(index)"
        >
          <ChevronDown v-if="!isExpanded(index)" class="h-3.5 w-3.5" />
          <ChevronUp v-else class="h-3.5 w-3.5" />
          {{ isExpanded(index) ? '收起' : '展开全部' }}
        </button>
      </div>
    </div>
  </div>
</template>
