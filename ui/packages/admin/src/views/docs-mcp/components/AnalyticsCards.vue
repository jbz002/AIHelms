<script setup lang="ts">
import { computed } from 'vue'
import type {
  DocsMcpStats,
  DocumentDashboardSummary,
} from '@aihelms/shared'
import { Database, BookOpen, FileText, Layers } from 'lucide-vue-next'

interface Props {
  stats: DocsMcpStats | null
  summary: DocumentDashboardSummary | null
}

const props = defineProps<Props>()

const bySource = computed(() => props.summary?.global.by_source ?? {})
const totalDocuments = computed(() => props.summary?.global.total_documents ?? 0)

const crawlCount = computed(() => bySource.value.crawl ?? 0)
const uploadCount = computed(() => bySource.value.upload ?? 0)
</script>

<template>
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-3 lg:grid-cols-4">
    <div class="rounded-lg border border-gray-200 bg-white p-4">
      <div class="flex items-center gap-3">
        <div class="rounded-lg bg-blue-50 p-2"><Database class="h-5 w-5 text-blue-600" /></div>
        <div>
          <p class="text-sm text-gray-500">知识库总量</p>
          <p class="text-2xl font-bold text-gray-900">{{ stats?.totalChunks ?? 0 }}</p>
          <p class="text-xs text-gray-400">chunks</p>
        </div>
      </div>
    </div>
    <div class="rounded-lg border border-gray-200 bg-white p-4">
      <div class="flex items-center gap-3">
        <div class="rounded-lg bg-emerald-50 p-2"><BookOpen class="h-5 w-5 text-emerald-600" /></div>
        <div>
          <p class="text-sm text-gray-500">文档库 / 版本</p>
          <p class="text-2xl font-bold text-gray-900">{{ stats?.libraryCount ?? 0 }} / {{ stats?.versionCount ?? 0 }}</p>
          <p class="text-xs text-gray-400">libraries / versions</p>
        </div>
      </div>
    </div>
    <div class="rounded-lg border border-gray-200 bg-white p-4">
      <div class="flex items-center gap-3">
        <div class="rounded-lg bg-purple-50 p-2"><FileText class="h-5 w-5 text-purple-600" /></div>
        <div>
          <p class="text-sm text-gray-500">已索引页面</p>
          <p class="text-2xl font-bold text-gray-900">{{ stats?.totalPages ?? 0 }}</p>
          <p class="text-xs text-gray-400">pages</p>
        </div>
      </div>
    </div>
    <div class="rounded-lg border border-gray-200 bg-white p-4">
      <div class="flex items-center gap-3">
        <div class="rounded-lg bg-indigo-50 p-2"><Layers class="h-5 w-5 text-indigo-600" /></div>
        <div>
          <p class="text-sm text-gray-500">文档总数 / 来源</p>
          <p class="text-2xl font-bold text-gray-900">{{ totalDocuments }}</p>
          <p class="text-xs text-gray-400">爬取 {{ crawlCount }} · 上传 {{ uploadCount }}</p>
        </div>
      </div>
    </div>
  </div>
</template>
