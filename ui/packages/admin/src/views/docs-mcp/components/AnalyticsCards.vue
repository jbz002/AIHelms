<script setup lang="ts">
import { computed } from 'vue'
import type {
  DocsMcpStats,
  DocsMcpLibrary,
  DocumentDashboardSummary,
} from '@aihelms/shared'
import { Database, BookOpen, FileText, PieChart, Layers, Activity, HardDrive } from 'lucide-vue-next'

interface Props {
  stats: DocsMcpStats | null
  summary: DocumentDashboardSummary | null
  libraries: DocsMcpLibrary[]
}

const props = defineProps<Props>()

const INDEXING_STATUSES = new Set(['running', 'queued', 'updating', 'indexing'])

const byStatus = computed(() => props.summary?.global.by_status ?? {})
const bySource = computed(() => props.summary?.global.by_source ?? {})
const totalDocuments = computed(() => props.summary?.global.total_documents ?? 0)
const uploadStorageBytes = computed(() => props.summary?.global.upload_storage_bytes ?? 0)

const ingested = computed(() => byStatus.value.ingested ?? 0)
const ingesting = computed(() => byStatus.value.ingesting ?? 0)
const pending = computed(() => byStatus.value.pending ?? 0)
const failed = computed(() => byStatus.value.failed ?? 0)
const crawlCount = computed(() => bySource.value.crawl ?? 0)
const uploadCount = computed(() => bySource.value.upload ?? 0)

const indexingVersionCount = computed(() =>
  props.libraries.reduce(
    (n, lib) => n + lib.versions.filter((v) => INDEXING_STATUSES.has(v.status)).length,
    0,
  ),
)

const lastIndexedAt = computed(() => {
  const ts = props.libraries
    .flatMap((lib) => lib.versions.map((v) => v.indexedAt))
    .filter((x): x is string => !!x)
    .sort()
  return ts.length ? ts[ts.length - 1] : ''
})

function fmtBytes(n: number): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(n) / Math.log(1024))
  return `${(n / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function fmtDate(iso: string): string {
  if (!iso) return '—'
  return iso.replace('T', ' ').slice(0, 16)
}
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
        <div class="rounded-lg bg-amber-50 p-2"><PieChart class="h-5 w-5 text-amber-600" /></div>
        <div>
          <p class="text-sm text-gray-500">入库状态分布</p>
          <p class="text-2xl font-bold text-gray-900">{{ totalDocuments }}</p>
          <p class="text-xs text-gray-400">已入库 {{ ingested }} · 入库中 {{ ingesting }} · 未入库 {{ pending }}<span v-if="failed"> · 失败 {{ failed }}</span></p>
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
    <div class="rounded-lg border border-gray-200 bg-white p-4">
      <div class="flex items-center gap-3">
        <div class="rounded-lg bg-rose-50 p-2"><Activity class="h-5 w-5 text-rose-600" /></div>
        <div>
          <p class="text-sm text-gray-500">索引活动</p>
          <p class="text-2xl font-bold text-gray-900">{{ indexingVersionCount }} <span class="text-sm font-normal text-gray-500">个版本索引中</span></p>
          <p class="text-xs text-gray-400">最近索引 {{ fmtDate(lastIndexedAt) }}</p>
        </div>
      </div>
    </div>
    <div class="rounded-lg border border-gray-200 bg-white p-4">
      <div class="flex items-center gap-3">
        <div class="rounded-lg bg-cyan-50 p-2"><HardDrive class="h-5 w-5 text-cyan-600" /></div>
        <div>
          <p class="text-sm text-gray-500">上传存储占用</p>
          <p class="text-2xl font-bold text-gray-900">{{ fmtBytes(uploadStorageBytes) }}</p>
          <p class="text-xs text-gray-400">上传文件累计</p>
        </div>
      </div>
    </div>
  </div>
</template>
