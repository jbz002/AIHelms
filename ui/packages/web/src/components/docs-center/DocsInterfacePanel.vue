<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type {
  LibraryEndpoint,
  LibraryInterfacesResult,
  LibraryBatchExtractStatus,
  HttpMethod,
} from '@aihelms/shared'
import {
  getLibraryInterfaces,
  extractLibraryInterfaces,
  getLibraryExtractStatus,
  toast,
} from '@aihelms/shared'
import { Loader2, Code2, Wand2, Search, ChevronDown, ChevronRight } from 'lucide-vue-next'
import DocsTryItOut from './DocsTryItOut.vue'

interface Props {
  libraryName: string
  canManage: boolean
}
const props = defineProps<Props>()
const { t } = useI18n()

const loading = ref(false)
const result = ref<LibraryInterfacesResult | null>(null)
const selectedKey = ref<string | null>(null)

const submitting = ref(false)
const batchStatus = ref<LibraryBatchExtractStatus | null>(null)
let batchTimer: number | null = null

const isBatchRunning = computed(
  () => batchStatus.value?.status === 'queued' || batchStatus.value?.status === 'running',
)
const isBusy = computed(() => isBatchRunning.value || submitting.value)

const METHOD_COLOR: Record<HttpMethod, string> = {
  get: 'bg-green-50 text-green-700 ring-green-200',
  post: 'bg-blue-50 text-blue-700 ring-blue-200',
  put: 'bg-amber-50 text-amber-700 ring-amber-200',
  delete: 'bg-red-50 text-red-700 ring-red-200',
  patch: 'bg-purple-50 text-purple-700 ring-purple-200',
}

const items = computed(() =>
  (result.value?.endpoints ?? []).map((e) => ({
    key: String(e.id),
    method: e.method,
    path: e.path,
    summary: e.summary,
    category: e.category,
  })),
)
const selected = computed<LibraryEndpoint | null>(
  () => result.value?.endpoints.find((e) => String(e.id) === selectedKey.value) ?? null,
)

const keyword = ref('')
const collapsedTags = ref<Set<string>>(new Set())
const filteredItems = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return items.value
  return items.value.filter(
    (e) =>
      e.path.toLowerCase().includes(kw) ||
      (e.summary ?? '').toLowerCase().includes(kw) ||
      e.method.includes(kw) ||
      e.category.toLowerCase().includes(kw),
  )
})
const groups = computed(() => {
  const map = new Map<string, typeof items.value>()
  for (const e of filteredItems.value) {
    const tag = e.category || t('docs.interfaces.defaultCategory')
    if (!map.has(tag)) map.set(tag, [])
    map.get(tag)!.push(e)
  }
  return Array.from(map, ([tag, list]) => ({ tag, items: list }))
})

function toggleTag(tag: string): void {
  const next = new Set(collapsedTags.value)
  if (next.has(tag)) next.delete(tag)
  else next.add(tag)
  collapsedTags.value = next
}

async function load(): Promise<void> {
  loading.value = true
  try {
    result.value = await getLibraryInterfaces(props.libraryName)
    if (result.value.endpoints.length && !selectedKey.value) {
      selectedKey.value = String(result.value.endpoints[0].id)
    }
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

async function confirmBatchExtract(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  try {
    batchStatus.value = await extractLibraryInterfaces(props.libraryName)
    startBatchPoll()
    toast.success(t('docs.interfaces.batchSubmitted'))
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    submitting.value = false
  }
}

function startBatchPoll(): void {
  stopBatchPoll()
  batchTimer = window.setInterval(pollBatch, 5000)
}
function stopBatchPoll(): void {
  if (batchTimer !== null) {
    window.clearInterval(batchTimer)
    batchTimer = null
  }
}
async function pollBatch(): Promise<void> {
  try {
    const latest = await getLibraryExtractStatus(props.libraryName)
    batchStatus.value = latest
    if (!latest || !isBatchRunning.value) {
      stopBatchPoll()
      if (latest?.status === 'completed') {
        const skip = latest.skipped_documents ?? 0
        toast.success(
          t('docs.interfaces.batchDone', { n: latest.total_endpoints ?? 0 }) +
            (skip ? t('docs.interfaces.batchSkipped', { n: skip }) : ''),
        )
        await load()
      } else if (latest?.status === 'failed') {
        toast.error(t('docs.interfaces.batchFailed'))
      }
    }
  } catch {
    stopBatchPoll()
  }
}

watch(
  () => props.libraryName,
  () => {
    selectedKey.value = null
    result.value = null
    load()
    getLibraryExtractStatus(props.libraryName).then((s) => {
      batchStatus.value = s
      if (s && (s.status === 'queued' || s.status === 'running')) startBatchPoll()
    })
  },
)

onMounted(() => {
  load()
  getLibraryExtractStatus(props.libraryName).then((s) => {
    batchStatus.value = s
    if (s && (s.status === 'queued' || s.status === 'running')) startBatchPoll()
  })
})
onUnmounted(stopBatchPoll)
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-2">
      <h2 class="text-base font-semibold text-slate-900 truncate">
        {{ t('docs.interfaces.title') }} · {{ libraryName }}
      </h2>
      <span v-if="result" class="text-xs text-slate-500">{{ t('docs.interfaces.total', { n: result.total }) }}</span>
      <div v-if="canManage" class="ml-auto">
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-60"
          :disabled="isBusy"
          @click="confirmBatchExtract"
        >
          <Loader2 v-if="isBatchRunning || submitting" class="h-4 w-4 animate-spin" />
          <Wand2 v-else class="h-4 w-4" />
          {{ isBatchRunning ? t('docs.interfaces.extracting', { done: batchStatus?.completed_documents ?? 0, total: batchStatus?.total_documents ?? 0 }) : t('docs.interfaces.batchExtract') }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="flex h-60 items-center justify-center">
      <Loader2 class="h-6 w-6 animate-spin text-slate-400" />
    </div>

    <div
      v-else-if="!result || !result.endpoints.length"
      class="flex h-60 flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white"
    >
      <Code2 class="h-10 w-10 text-slate-300" />
      <p class="mt-3 px-6 text-center text-sm text-slate-500">{{ t('docs.interfaces.empty') }}</p>
    </div>

    <div v-else class="flex flex-col gap-4 lg:flex-row">
      <!-- 接口列表 -->
      <div class="flex w-full shrink-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm lg:w-80">
        <div class="border-b border-slate-100 p-3">
          <div class="relative">
            <Search class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              v-model="keyword"
              :placeholder="t('docs.interfaces.searchPlaceholder')"
              class="w-full rounded-md border border-slate-200 py-1.5 pl-8 pr-2 text-sm focus:border-purple-400 focus:outline-none"
            />
          </div>
        </div>
        <div class="max-h-[60vh] flex-1 overflow-y-auto p-2">
          <div v-for="g in groups" :key="g.tag" class="mb-2">
            <button
              type="button"
              class="flex w-full items-center gap-1 rounded px-1 py-1 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-700"
              @click="toggleTag(g.tag)"
            >
              <ChevronDown v-if="!collapsedTags.has(g.tag)" class="h-3.5 w-3.5 shrink-0" />
              <ChevronRight v-else class="h-3.5 w-3.5 shrink-0" />
              <span class="truncate">{{ g.tag }}</span>
              <span class="ml-auto font-normal text-slate-400">{{ g.items.length }}</span>
            </button>
            <div v-show="!collapsedTags.has(g.tag)">
              <button
                v-for="item in g.items"
                :key="item.key"
                type="button"
                class="mb-0.5 flex w-full items-center gap-2 rounded-md px-2 py-2 text-left"
                :class="selectedKey === item.key ? 'bg-purple-50' : 'hover:bg-slate-50'"
                @click="selectedKey = item.key"
              >
                <span
                  class="inline-flex w-14 shrink-0 justify-center rounded px-1.5 py-0.5 font-mono text-xs font-semibold ring-1 ring-inset"
                  :class="METHOD_COLOR[item.method]"
                >{{ item.method.toUpperCase() }}</span>
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-sm font-medium text-slate-700">{{ item.summary || item.path }}</span>
                  <span v-if="item.summary" class="block truncate font-mono text-xs text-slate-400">{{ item.path }}</span>
                </span>
              </button>
            </div>
          </div>
          <div v-if="!groups.length" class="py-8 text-center text-sm text-slate-300">{{ t('docs.interfaces.noMatch') }}</div>
        </div>
      </div>

      <!-- 接口详情 + TryItOut -->
      <div class="flex flex-1 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <template v-if="selected">
          <div class="border-b border-slate-100 px-4 py-3">
            <div class="flex items-center gap-2">
              <span
                class="inline-flex w-16 justify-center rounded px-2 py-0.5 font-mono text-xs font-semibold ring-1 ring-inset"
                :class="METHOD_COLOR[selected.method]"
              >{{ selected.method.toUpperCase() }}</span>
              <span class="font-mono text-sm text-slate-800">{{ selected.path }}</span>
            </div>
            <p v-if="selected.summary" class="mt-1.5 text-sm text-slate-600">{{ selected.summary }}</p>
            <p v-if="selected.operation.description" class="mt-1 whitespace-pre-wrap text-xs text-slate-400">{{ selected.operation.description }}</p>
          </div>
          <div class="overflow-y-auto p-4">
            <DocsTryItOut
              :method="selected.method"
              :path="selected.path"
              :operation="selected.operation"
              :doc-id="selected.document_id"
              :library-name="libraryName"
            />
          </div>
        </template>
        <div v-else class="flex h-full items-center justify-center p-8 text-sm text-slate-400">
          {{ t('docs.interfaces.selectPrompt') }}
        </div>
      </div>
    </div>
  </div>
</template>
