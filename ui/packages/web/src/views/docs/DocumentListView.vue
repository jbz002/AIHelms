<script setup lang="ts">
import { ref, computed, onMounted, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import type { Document, DocsMcpVersion } from '@aihelms/shared'
import {
  getDocuments,
  deleteDocument,
  getDocsMcpLibraryDetail,
  deleteDocsMcpVersion,
  deleteLibrary,
  extractLibraryInterfaces,
  getLibraryExtractStatus,
  toast,
} from '@aihelms/shared'
import { Loader2, Upload, Code2, FileText, Trash2, Plus, RefreshCw, ArrowLeft, Wand2 } from 'lucide-vue-next'
import DocsUploadDialog from '../../components/docs-center/DocsUploadDialog.vue'
import DocsAddVersionDialog from '../../components/docs-center/DocsAddVersionDialog.vue'
import DocsExtractConfirmDialog from '../../components/docs-center/DocsExtractConfirmDialog.vue'
import { useDocsOwner } from '../../composables/useDocsOwner'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const libraryName = computed(() => route.params.libraryName as string)
const currentVersion = computed(() => (route.query.version as string) || '')
// 实际查看版本：路由显式选择 > 最新（与 docs-mcp 检索默认口径一致）
const effectiveVersion = computed(() => currentVersion.value || 'latest')
// select 代理：写时 router.replace 更新 query，读时取 effectiveVersion
const selectedVersion = computed<string>({
  get: () => effectiveVersion.value,
  set: (val: string) => {
    router.replace({ query: { ...route.query, version: val } })
  },
})

const { library, canManage } = useDocsOwner(libraryName)

const loading = ref(false)
const extractingLib = ref(false)
let libExtractTimer: number | null = null
const showExtractConfirm = ref(false)
const documents = ref<Document[]>([])
const uploadVisible = ref(false)
const addVersionVisible = ref(false)

const versions = ref<DocsMcpVersion[]>([])
const loadingVersions = ref(false)
const deletingVersion = ref(false)
let versionPollTimer: number | null = null

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

// 上传增量目标版本：空库无版本桶 → 建首个版本(nextVersion，默认 1.0.0)；否则当前选中版本
const uploadVersion = computed(() =>
  versions.value.length === 0 ? nextVersion.value : effectiveVersion.value,
)

const STATUS_BADGE: Record<string, string> = {
  pending: 'bg-slate-100 text-slate-600',
  ingesting: 'bg-blue-50 text-blue-700',
  ingested: 'bg-green-50 text-green-700',
  failed: 'bg-red-50 text-red-700',
  duplicate: 'bg-amber-50 text-amber-700',
}

function sourceLabel(s: string): string {
  return s === 'crawl' ? t('docs.doc.sourceType.crawl') : t('docs.doc.sourceType.upload')
}

async function loadVersions(): Promise<void> {
  loadingVersions.value = true
  try {
    const lib = await getDocsMcpLibraryDetail(libraryName.value)
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
    const res = await getDocuments(libraryName.value, undefined, undefined, 1, 100, effectiveVersion.value)
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
        router.replace({ query: { ...route.query, version: targetVer } })
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

function onUploaded(ver: string): void {
  uploadVisible.value = false
  // latest 桶已存在（增量到当前最新），直接刷；具体版本（含空库首建）异步生桶，轮询直到出现
  if (ver === 'latest') {
    loadVersions()
    load()
    return
  }
  startVersionPoll(ver)
}

async function onConfirmExtract(): Promise<void> {
  showExtractConfirm.value = false
  await handleLibraryExtract()
}

async function handleLibraryExtract(): Promise<void> {
  if (extractingLib.value) return
  extractingLib.value = true
  try {
    await extractLibraryInterfaces(libraryName.value)
    toast.success(t('docs.interfaces.batchSubmitted'))
    pollLibExtract()
  } catch (e) {
    toast.error((e as Error).message || t('docs.interfaces.batchFailed'))
    extractingLib.value = false
  }
}

function pollLibExtract(): void {
  stopLibExtract()
  libExtractTimer = window.setInterval(async () => {
    try {
      const s = await getLibraryExtractStatus(libraryName.value)
      if (!s || (s.status !== 'queued' && s.status !== 'running')) {
        stopLibExtract()
        extractingLib.value = false
        if (s?.status === 'completed') {
          const skip = s.skipped_documents ?? 0
          toast.success(
            t('docs.interfaces.batchDone', { n: s.total_endpoints ?? 0 }) +
              (skip ? t('docs.interfaces.batchSkipped', { n: skip }) : ''),
          )
        } else if (s?.status === 'failed') {
          toast.error(t('docs.interfaces.batchFailed'))
        }
        load()
      }
    } catch {
      stopLibExtract()
      extractingLib.value = false
    }
  }, 5000)
}

function stopLibExtract(): void {
  if (libExtractTimer) {
    window.clearInterval(libExtractTimer)
    libExtractTimer = null
  }
}

function onVersionAdded(ver: string): void {
  addVersionVisible.value = false
  startVersionPoll(ver)
}

function goDetail(doc: Document): void {
  router.push({ name: 'DocsDocumentDetail', params: { libraryName: libraryName.value, docId: doc.id } })
}

function goLibraryInterfaces(): void {
  router.push({ name: 'DocsLibraryInterfaces', params: { libraryName: libraryName.value } })
}

function goDocInterfaces(doc: Document): void {
  router.push({ name: 'DocsDocumentInterfaces', params: { libraryName: libraryName.value, docId: doc.id } })
}

function back(): void {
  router.push({ name: 'DocsLibraryList' })
}

async function handleDeleteVersion(): Promise<void> {
  if (deletingVersion.value) return
  // 空库：docs-mcp 无版本桶，删版本 = 删平台库记录
  if (versions.value.length === 0) {
    if (library.value === null) return
    if (!window.confirm(t('docs.version.confirmDeleteLast', { name: libraryName.value }))) return
    deletingVersion.value = true
    try {
      await deleteLibrary(library.value.id)
      toast.success(t('docs.version.deletedLast'))
      router.push({ name: 'DocsLibraryList' })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      deletingVersion.value = false
    }
    return
  }
  const ver = effectiveVersion.value
  const msg = isLastVersion.value
    ? t('docs.version.confirmDeleteLast', { name: libraryName.value })
    : t('docs.version.confirmDelete', { ver })
  if (!window.confirm(msg)) return
  deletingVersion.value = true
  try {
    await deleteDocsMcpVersion(libraryName.value, ver)
    if (isLastVersion.value) {
      toast.success(t('docs.version.deletedLast'))
      router.push({ name: 'DocsLibraryList' })
      return
    }
    toast.success(t('docs.version.deleted'))
    await router.replace({ query: { ...route.query, version: 'latest' } })
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

watch(libraryName, () => {
  router.replace({ query: { ...route.query, version: undefined } })
  loadVersions()
  load()
})

watch(currentVersion, () => {
  load()
})

onMounted(() => {
  loadVersions()
  load()
})

onUnmounted(() => {
  stopVersionPoll()
  stopLibExtract()
})
</script>

<template>
  <div class="mx-auto max-w-7xl px-6 py-8">
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <button class="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700" @click="back">
        <ArrowLeft class="h-4 w-4" />
        {{ t('docs.action.back') }}
      </button>
      <h1 class="text-base font-semibold text-slate-900">{{ libraryName }}</h1>
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
      <div v-if="canManage" class="flex items-center gap-1">
        <button
          class="inline-flex items-center gap-1 rounded-md bg-purple-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-purple-700"
          @click="addVersionVisible = true"
        >
          <Plus class="h-3.5 w-3.5" />
          {{ t('docs.version.add') }}
        </button>
        <button
          class="inline-flex items-center gap-1 rounded-md border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="deletingVersion"
          @click="handleDeleteVersion"
        >
          <Loader2 v-if="deletingVersion" class="h-3.5 w-3.5 animate-spin" />
          <Trash2 v-else class="h-3.5 w-3.5" />
          {{ t('docs.version.delete') }}
        </button>
      </div>
      <div v-if="canManage" class="ml-auto flex items-center gap-1">
        <button
          class="inline-flex items-center gap-1 rounded-md border border-purple-200 bg-purple-50 px-2.5 py-1 text-xs font-medium text-purple-700 hover:bg-purple-100 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="extractingLib"
          :title="t('docs.interfaces.batchHint')"
          @click="showExtractConfirm = true"
        >
          <Loader2 v-if="extractingLib" class="h-3.5 w-3.5 animate-spin" />
          <Wand2 v-else class="h-3.5 w-3.5" />
          {{ t('docs.interfaces.extractLib') }}
        </button>
        <button
          class="inline-flex items-center gap-1 rounded-md border border-purple-200 bg-purple-50 px-2.5 py-1 text-xs font-medium text-purple-700 hover:bg-purple-100"
          @click="uploadVisible = true"
        >
          <Upload class="h-3.5 w-3.5" />
          {{ versions.length === 0 ? t('docs.doc.upload') : t('docs.version.uploadIncremental') }}
        </button>
      </div>
      <button
        class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
        @click="goLibraryInterfaces"
      >
        <Code2 class="h-3.5 w-3.5" />
        {{ t('docs.interfaces.title') }}
      </button>
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
          <tr v-for="doc in documents" :key="doc.id" class="cursor-pointer hover:bg-slate-50" @click="goDetail(doc)">
            <td class="max-w-xs truncate px-3 py-2 font-medium text-slate-700">{{ doc.title || doc.source_id }}</td>
            <td class="px-3 py-2 text-slate-500">{{ sourceLabel(doc.source_type) }}</td>
            <td class="px-3 py-2">
              <span class="inline-flex rounded px-2 py-0.5 text-xs font-medium" :class="STATUS_BADGE[doc.ingest_status] ?? 'bg-slate-100 text-slate-600'">
                {{ t(`docs.doc.status.${doc.ingest_status}`) }}
              </span>
            </td>
            <td class="px-3 py-2 text-right">
              <div v-if="canManage" class="flex items-center justify-end gap-1">
                <button
                  class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-purple-600 hover:bg-purple-50"
                  @click.stop="goDocInterfaces(doc)"
                >
                  <Code2 class="h-3.5 w-3.5" />
                  {{ t('docs.doc.interfaces') }}
                </button>
                <button
                  class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                  @click.stop="handleDelete(doc)"
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

    <DocsUploadDialog :visible="uploadVisible" :library-name="libraryName" :version="uploadVersion" :lock-version="versions.length > 0" @uploaded="onUploaded" @close="uploadVisible = false" />
    <DocsAddVersionDialog :visible="addVersionVisible" :library-name="libraryName" :default-version="nextVersion" @uploaded="onVersionAdded" @close="addVersionVisible = false" />
    <DocsExtractConfirmDialog :visible="showExtractConfirm" :library-name="libraryName" @close="showExtractConfirm = false" @confirm="onConfirmExtract" />
  </div>
</template>
