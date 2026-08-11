<script setup lang="ts">
import { ref, computed, onMounted, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Document, DocsMcpVersion } from '@aihelms/shared'
import {
  getDocuments,
  extractDocumentInterfaces,
  getDocumentExtractStatus,
  deleteDocument,
  getDocsMcpLibraryDetail,
  deleteDocsMcpVersion,
  toast,
} from '@aihelms/shared'
import { Loader2, Upload, Wand2, FileText, Trash2, Plus, RefreshCw } from 'lucide-vue-next'
import DocsUploadDialog from './DocsUploadDialog.vue'
import DocsAddVersionDialog from './DocsAddVersionDialog.vue'

interface Props {
  libraryName: string
  canManage: boolean
}
const props = defineProps<Props>()
const emit = defineEmits<{ 'library-deleted': [] }>()
const { t } = useI18n()

const loading = ref(false)
const documents = ref<Document[]>([])
const uploadVisible = ref(false)
const addVersionVisible = ref(false)
const extracting = ref<Set<number>>(new Set())
const extractTimers = new Map<number, number>()

const versions = ref<DocsMcpVersion[]>([])
const loadingVersions = ref(false)
const selectedVersion = ref<string>('latest')
const deletingVersion = ref(false)
let versionPollTimer: number | null = null

const effectiveVersion = computed(() => selectedVersion.value || 'latest')

// 版本下拉：最新（持续锁定最新 semver）+ 库内全部具体版本；空 ref.version 一律跳过
const versionOptions = computed(() => {
  const options: Array<{ value: string; label: string }> = [
    { value: 'latest', label: t('docs.version.latest') },
  ]
  for (const v of versions.value) {
    const ver = v.ref?.version || ''
    if (!ver) continue
    options.push({ value: ver, label: ver })
  }
  return options
})

// 末版本：删它 = 删整个文档库（docs-mcp 库随末版本消失）
const isLastVersion = computed(() => versions.value.length <= 1)

// 新增版本默认号：库内最大语义版本 patch+1，无可解析版本则 1.0.0
const nextVersion = computed(() => {
  let best: [number, number, number] | null = null
  for (const v of versions.value) {
    const m = (v.ref?.version || '').replace(/^v/i, '').match(/^(\d+)\.(\d+)\.(\d+)/)
    if (!m) continue
    const cur = [Number(m[1]), Number(m[2]), Number(m[3])] as [number, number, number]
    if (
      !best ||
      cur[0] > best[0] ||
      (cur[0] === best[0] && (cur[1] > best[1] || (cur[1] === best[1] && cur[2] > best[2])))
    ) {
      best = cur
    }
  }
  return best ? `${best[0]}.${best[1]}.${best[2] + 1}` : '1.0.0'
})

const STATUS_BADGE: Record<string, string> = {
  pending: 'bg-slate-100 text-slate-600',
  ingesting: 'bg-blue-50 text-blue-700',
  ingested: 'bg-green-50 text-green-700',
  failed: 'bg-red-50 text-red-700',
  duplicate: 'bg-amber-50 text-amber-700',
}

async function loadVersions(): Promise<void> {
  loadingVersions.value = true
  try {
    const lib = await getDocsMcpLibraryDetail(props.libraryName)
    versions.value = lib?.versions ?? []
  } catch {
    // 库不存在于 docs-mcp（新建空库尚未入库）→ 无版本
    versions.value = []
  } finally {
    loadingVersions.value = false
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const res = await getDocuments(props.libraryName, undefined, undefined, 1, 100, effectiveVersion.value)
    documents.value = res.items
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

function refreshAll(): void {
  loadVersions()
  load()
}

// 新增版本/上传增量后 docs-mcp 版本桶异步生成，轮询直到目标版本出现或超时
function startVersionPoll(targetVer: string): void {
  stopVersionPoll()
  let attempts = 0
  const maxAttempts = 20
  versionPollTimer = window.setInterval(async () => {
    attempts++
    await loadVersions()
    await load()
    if (versions.value.some((v) => v.ref?.version === targetVer) || attempts >= maxAttempts) {
      stopVersionPoll()
      if (versions.value.some((v) => v.ref?.version === targetVer)) {
        selectedVersion.value = targetVer
      }
    }
  }, 3000)
}

function stopVersionPoll(): void {
  if (versionPollTimer !== null) {
    window.clearInterval(versionPollTimer)
    versionPollTimer = null
  }
}

async function handleExtract(doc: Document): Promise<void> {
  if (extracting.value.has(doc.id)) return
  extracting.value = new Set(extracting.value).add(doc.id)
  try {
    await extractDocumentInterfaces(doc.id)
    toast.success(t('docs.doc.extractQueued'))
    startPoll(doc.id)
  } catch (e) {
    extracting.value = new Set([...extracting.value].filter((id) => id !== doc.id))
    const msg = (e as Error).message || ''
    if (msg.includes('进行中') || msg.includes('409')) {
      toast.error(t('docs.doc.extractBusy'))
    } else {
      toast.error(msg)
    }
  }
}

function startPoll(docId: number): void {
  stopPoll(docId)
  const timer = window.setInterval(() => pollOnce(docId), 5000)
  extractTimers.set(docId, timer)
}
function stopPoll(docId: number): void {
  const timer = extractTimers.get(docId)
  if (timer !== undefined) {
    window.clearInterval(timer)
    extractTimers.delete(docId)
  }
}
async function pollOnce(docId: number): Promise<void> {
  try {
    const s = await getDocumentExtractStatus(docId)
    if (!s || s.status === 'completed' || s.status === 'failed') {
      stopPoll(docId)
      extracting.value = new Set([...extracting.value].filter((id) => id !== docId))
      if (s?.status === 'completed') {
        toast.success(t('docs.doc.extractDone', { n: s.endpoint_count ?? 0 }))
      } else if (s?.status === 'failed') {
        toast.error(t('docs.doc.extractFailed'))
      }
    }
  } catch {
    stopPoll(docId)
    extracting.value = new Set([...extracting.value].filter((id) => id !== docId))
  }
}

function onUploaded(): void {
  loadVersions()
  load()
}

function onVersionAdded(ver: string): void {
  addVersionVisible.value = false
  startVersionPoll(ver)
}

async function handleDeleteVersion(): Promise<void> {
  if (deletingVersion.value || versions.value.length === 0) return
  const ver = effectiveVersion.value
  const msg = isLastVersion.value
    ? t('docs.version.confirmDeleteLast', { name: props.libraryName })
    : t('docs.version.confirmDelete', { ver })
  if (!window.confirm(msg)) return
  deletingVersion.value = true
  try {
    await deleteDocsMcpVersion(props.libraryName, ver)
    if (isLastVersion.value) {
      toast.success(t('docs.version.deletedLast'))
      emit('library-deleted')
      return
    }
    toast.success(t('docs.version.deleted'))
    selectedVersion.value = 'latest'
    await loadVersions()
    await load()
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    deletingVersion.value = false
  }
}

async function handleDelete(doc: Document): Promise<void> {
  if (!window.confirm(t('docs.doc.confirmDelete'))) return
  try {
    await deleteDocument(doc.id)
    toast.success(t('docs.doc.deleteSuccess'))
    load()
  } catch (e) {
    toast.error((e as Error).message)
  }
}

watch(
  () => props.libraryName,
  () => {
    selectedVersion.value = 'latest'
    loadVersions()
    load()
  },
)

watch(effectiveVersion, () => {
  load()
})

onMounted(() => {
  loadVersions()
  load()
})

onUnmounted(() => {
  stopVersionPoll()
  for (const id of extractTimers.keys()) {
    stopPoll(id)
  }
})
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-2">
      <h2 class="text-base font-semibold text-slate-900">{{ t('docs.doc.title') }} · {{ libraryName }}</h2>
      <select
        v-model="selectedVersion"
        :disabled="loadingVersions"
        class="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 focus:border-purple-400 focus:outline-none disabled:bg-slate-50"
        :title="t('docs.version.switch')"
      >
        <option v-for="o in versionOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <button
        class="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50"
        :disabled="loading"
        @click="refreshAll"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': loading }" />
      </button>
      <div v-if="canManage" class="ml-auto flex items-center gap-1">
        <button
          class="inline-flex items-center gap-1 rounded-md bg-purple-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-purple-700"
          @click="addVersionVisible = true"
        >
          <Plus class="h-3.5 w-3.5" />
          {{ t('docs.version.add') }}
        </button>
        <button
          class="inline-flex items-center gap-1 rounded-md border border-purple-200 bg-purple-50 px-2.5 py-1 text-xs font-medium text-purple-700 hover:bg-purple-100 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="versions.length === 0"
          :title="versions.length === 0 ? t('docs.version.uploadDisabled') : ''"
          @click="uploadVisible = true"
        >
          <Upload class="h-3.5 w-3.5" />
          {{ t('docs.version.uploadIncremental') }}
        </button>
        <button
          class="inline-flex items-center gap-1 rounded-md border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="deletingVersion || versions.length === 0"
          @click="handleDeleteVersion"
        >
          <Loader2 v-if="deletingVersion" class="h-3.5 w-3.5 animate-spin" />
          <Trash2 v-else class="h-3.5 w-3.5" />
          {{ t('docs.version.delete') }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="flex h-60 items-center justify-center">
      <Loader2 class="h-6 w-6 animate-spin text-slate-400" />
    </div>

    <div
      v-else-if="!documents.length"
      class="flex h-60 flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white"
    >
      <FileText class="h-10 w-10 text-slate-300" />
      <p class="mt-3 px-6 text-center text-sm text-slate-500">{{ t('docs.doc.empty') }}</p>
    </div>

    <div v-else class="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <table class="w-full text-sm">
        <thead class="bg-slate-50 text-xs text-slate-500">
          <tr>
            <th class="px-3 py-2 text-left font-medium">{{ t('docs.doc.col.title') }}</th>
            <th class="px-3 py-2 text-left font-medium">{{ t('docs.doc.col.type') }}</th>
            <th class="px-3 py-2 text-left font-medium">{{ t('docs.doc.col.status') }}</th>
            <th class="px-3 py-2 text-right font-medium">{{ t('docs.doc.col.actions') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-for="doc in documents" :key="doc.id" class="hover:bg-slate-50">
            <td class="max-w-xs truncate px-3 py-2 text-slate-700">{{ doc.title || doc.source_id }}</td>
            <td class="px-3 py-2 text-slate-500">{{ doc.source_type }}</td>
            <td class="px-3 py-2">
              <span class="inline-flex rounded px-2 py-0.5 text-xs font-medium" :class="STATUS_BADGE[doc.ingest_status] ?? 'bg-slate-100 text-slate-600'">
                {{ t(`docs.doc.status.${doc.ingest_status}`) }}
              </span>
            </td>
            <td class="px-3 py-2 text-right">
              <div v-if="canManage" class="flex items-center justify-end gap-1">
                <button
                  class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-purple-600 hover:bg-purple-50 disabled:opacity-50"
                  :disabled="extracting.has(doc.id) || doc.ingest_status !== 'ingested'"
                  @click="handleExtract(doc)"
                >
                  <Loader2 v-if="extracting.has(doc.id)" class="h-3.5 w-3.5 animate-spin" />
                  <Wand2 v-else class="h-3.5 w-3.5" />
                  {{ extracting.has(doc.id) ? t('docs.doc.extracting') : t('docs.doc.extract') }}
                </button>
                <button
                  class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                  @click="handleDelete(doc)"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                  {{ t('docs.doc.delete') }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <DocsUploadDialog :visible="uploadVisible" :library-name="libraryName" :version="effectiveVersion" @uploaded="onUploaded" @close="uploadVisible = false" />
    <DocsAddVersionDialog :visible="addVersionVisible" :library-name="libraryName" :default-version="nextVersion" @uploaded="onVersionAdded" @close="addVersionVisible = false" />
  </div>
</template>
