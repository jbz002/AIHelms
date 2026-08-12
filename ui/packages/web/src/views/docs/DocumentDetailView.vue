<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { MdEditor, MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import type { Document } from '@aihelms/shared'
import {
  getDocument,
  updateDocument,
  ingestDocument,
  extractDocumentInterfaces,
  getDocumentExtractStatus,
  toast,
} from '@aihelms/shared'
import { ArrowLeft, Save, Loader2, Code2 } from 'lucide-vue-next'
import { useDocsOwner } from '../../composables/useDocsOwner'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()

const libraryName = computed(() => route.params.libraryName as string)
const docId = computed(() => Number(route.params.docId))
const { canManage } = useDocsOwner(libraryName)

const doc = ref<Document | null>(null)
const loading = ref(false)
const saving = ref(false)
const editContent = ref('')
let cancelled = false

const STATUS_BADGE: Record<string, string> = {
  pending: 'bg-slate-100 text-slate-600',
  ingesting: 'bg-blue-50 text-blue-700',
  ingested: 'bg-green-50 text-green-700',
  failed: 'bg-red-50 text-red-700',
  duplicate: 'bg-amber-50 text-amber-700',
}

function editorLanguage(): string {
  return locale.value === 'zh-CN' ? 'zh-CN' : 'en-US'
}

function sourceLabel(s: string): string {
  return s === 'crawl' ? t('docs.doc.sourceType.crawl') : t('docs.doc.sourceType.upload')
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function loadDocument(): Promise<void> {
  loading.value = true
  cancelled = false
  doc.value = null
  try {
    doc.value = await getDocument(docId.value)
    editContent.value = doc.value?.content ?? ''
  } catch (e) {
    toast.error((e as Error).message || t('docs.doc.loadFail'))
  } finally {
    loading.value = false
  }
}

// 入库走 celery 异步：先派发任务，再轮询单文档状态直到终态
async function reingestInBackground(): Promise<void> {
  try {
    await ingestDocument(docId.value)
  } catch (e) {
    toast.error((e as Error).message || t('docs.doc.reingestSubmitFail'))
    return
  }
  for (let i = 0; i < 40; i++) {
    if (cancelled) return
    await sleep(1500)
    try {
      const d = await getDocument(docId.value)
      doc.value = d
      if (d.ingest_status === 'ingested') {
        toast.success(t('docs.doc.reingestDone'))
        void triggerExtract()
        return
      }
      if (d.ingest_status === 'failed') {
        toast.error(t('docs.doc.reingestFailed', { msg: d.error_message || '' }))
        return
      }
    } catch {
      // 单次查询失败不中断轮询
    }
  }
}

// 入库完成后自动重新提取接口（读平台 DB content，不依赖 docs-mcp 入库结果）
async function triggerExtract(): Promise<void> {
  try {
    await extractDocumentInterfaces(docId.value)
    toast.info(t('docs.doc.extractRequeued'))
  } catch (e) {
    // 409 进行中 / 400 内容为空 / 403 无权限 —— 仅 toast，不阻断主流程
    toast.error((e as Error).message || t('docs.doc.extractFailed'))
    return
  }
  for (let i = 0; i < 60; i++) {
    if (cancelled) return
    await sleep(5000)
    try {
      const s = await getDocumentExtractStatus(docId.value)
      if (!s) return
      if (s.status === 'completed') {
        toast.success(t('docs.doc.extractDone', { n: s.endpoint_count ?? 0 }))
        return
      }
      if (s.status === 'failed') {
        toast.error(t('docs.doc.extractFailed'))
        return
      }
    } catch {
      // 单次查询失败不中断轮询
    }
  }
}

async function handleSave(): Promise<void> {
  if (!doc.value || saving.value) return
  saving.value = true
  try {
    const updated = await updateDocument(docId.value, { content: editContent.value })
    doc.value = updated
    toast.success(t('docs.doc.saved'))
    // 内容变更会重置 ingest_status=pending，自动后台重新入库（无需手动按钮）
    if (updated.ingest_status === 'pending') {
      toast.info(t('docs.doc.contentChanged'))
      void reingestInBackground()
    }
  } catch (e) {
    toast.error((e as Error).message || t('docs.doc.saveFail'))
  } finally {
    saving.value = false
  }
}

function goInterfaces(): void {
  router.push({ name: 'DocsDocumentInterfaces', params: { libraryName: libraryName.value, docId: docId.value } })
}

function back(): void {
  router.push({ name: 'DocsDocumentList', params: { libraryName: libraryName.value } })
}

onMounted(loadDocument)
onUnmounted(() => {
  cancelled = true
})
</script>

<template>
  <div class="mx-auto max-w-7xl px-6 py-8">
    <div class="mb-4 flex items-center gap-3">
      <button class="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700" @click="back">
        <ArrowLeft class="h-4 w-4" />
        {{ t('docs.action.back') }}
      </button>
      <h1 class="min-w-0 flex-1 truncate text-base font-semibold text-slate-900">{{ doc?.title || `#${docId}` }}</h1>
    </div>

    <div v-if="loading" class="flex h-60 items-center justify-center">
      <Loader2 class="h-6 w-6 animate-spin text-slate-400" />
    </div>

    <template v-else-if="doc">
      <div class="mb-3 flex flex-wrap items-center gap-2">
        <span class="inline-flex rounded px-2 py-0.5 text-xs font-medium" :class="STATUS_BADGE[doc.ingest_status] ?? 'bg-slate-100 text-slate-600'">
          {{ t(`docs.doc.status.${doc.ingest_status}`) }}
        </span>
        <span class="text-xs text-slate-500">{{ sourceLabel(doc.source_type) }} · {{ t('docs.doc.chunks', { n: doc.chunk_count }) }}</span>
        <div class="ml-auto flex items-center gap-2">
          <button
            class="inline-flex items-center gap-1 rounded-md bg-purple-50 px-3 py-1.5 text-xs font-medium text-purple-700 hover:bg-purple-100"
            @click="goInterfaces"
          >
            <Code2 class="h-3 w-3" />
            {{ t('docs.doc.interfaces') }}
          </button>
          <button
            v-if="canManage"
            class="inline-flex items-center gap-1 rounded-md bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100 disabled:opacity-50"
            :disabled="saving"
            @click="handleSave"
          >
            <Loader2 v-if="saving" class="h-3 w-3 animate-spin" />
            <Save v-else class="h-3 w-3" />
            {{ t('docs.library.save') }}
          </button>
        </div>
      </div>

      <div v-if="!canManage" class="mb-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-500">
        {{ t('docs.doc.readonly') }}
      </div>

      <div class="rounded-lg border border-slate-200 bg-white">
        <MdEditor
          v-if="canManage"
          v-model="editContent"
          :toolbars-exclude="['github', 'prettier']"
          :language="editorLanguage()"
          input-box-width="38%"
          style="height: 60vh"
        />
        <MdPreview v-else :model-value="doc.content" :language="editorLanguage()" />
      </div>

      <div class="mt-4 rounded-lg border border-slate-200 bg-white p-4">
        <h3 class="mb-2 text-xs font-medium uppercase text-slate-500">{{ t('docs.doc.meta.title') }}</h3>
        <div class="grid grid-cols-2 gap-x-8 gap-y-1.5 text-sm">
          <div class="text-slate-500">{{ t('docs.doc.meta.library') }}</div>
          <div class="text-slate-900">{{ doc.library }}</div>
          <div v-if="doc.version" class="text-slate-500">{{ t('docs.doc.meta.version') }}</div>
          <div v-if="doc.version" class="text-slate-900">{{ doc.version }}</div>
          <div class="text-slate-500">{{ t('docs.doc.meta.sourceType') }}</div>
          <div class="text-slate-900">{{ sourceLabel(doc.source_type) }}</div>
          <div class="text-slate-500">{{ t('docs.doc.meta.contentHash') }}</div>
          <div class="font-mono text-xs text-slate-500">{{ doc.content_hash || '-' }}</div>
          <div v-if="doc.error_message" class="text-slate-500">{{ t('docs.doc.meta.errorMessage') }}</div>
          <div v-if="doc.error_message" class="text-red-600">{{ doc.error_message }}</div>
        </div>
      </div>
    </template>
  </div>
</template>
