<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { MdEditor } from 'md-editor-v3'
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
import { Save, Loader2, X } from 'lucide-vue-next'

interface Props {
  visible: boolean
  docId: number | null
  libraryName: string
}
const props = defineProps<Props>()
const emit = defineEmits<{ close: []; saved: [docId: number] }>()
const { t, locale } = useI18n()

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
  if (props.docId === null) return
  loading.value = true
  cancelled = false
  doc.value = null
  try {
    doc.value = await getDocument(props.docId)
    editContent.value = doc.value?.content ?? ''
  } catch (e) {
    toast.error((e as Error).message || t('docs.doc.loadFail'))
  } finally {
    loading.value = false
  }
}

// 入库走 celery 异步：先派发任务，再轮询单文档状态直到终态
async function reingestInBackground(): Promise<void> {
  if (props.docId === null) return
  try {
    await ingestDocument(props.docId)
  } catch (e) {
    toast.error((e as Error).message || t('docs.doc.reingestSubmitFail'))
    return
  }
  for (let i = 0; i < 40; i++) {
    if (cancelled) return
    await sleep(1500)
    try {
      const d = await getDocument(props.docId)
      doc.value = d
      if (d.ingest_status === 'ingested') {
        toast.success(t('docs.doc.reingestDone'))
        emit('saved', props.docId)
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
  if (props.docId === null) return
  try {
    await extractDocumentInterfaces(props.docId)
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
      const s = await getDocumentExtractStatus(props.docId)
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
  if (!doc.value || saving.value || props.docId === null) return
  saving.value = true
  try {
    const updated = await updateDocument(props.docId, { content: editContent.value })
    doc.value = updated
    toast.success(t('docs.doc.saved'))
    emit('saved', props.docId)
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

watch(
  () => [props.visible, props.docId] as const,
  ([vis]) => {
    if (vis) loadDocument()
    else cancelled = true
  },
)

onUnmounted(() => {
  cancelled = true
})
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[9999] flex justify-end bg-black/40">
      <div class="flex h-full w-4/5 min-w-0 flex-col bg-white shadow-xl">
        <div class="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
          <h3 class="min-w-0 flex-1 truncate text-base font-semibold text-slate-900">{{ doc?.title || `#${docId}` }}</h3>
          <button class="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600" @click="emit('close')">
            <X class="h-4 w-4" />
          </button>
        </div>

        <div v-if="loading" class="flex flex-1 items-center justify-center">
          <Loader2 class="h-6 w-6 animate-spin text-slate-400" />
        </div>

        <template v-else-if="doc">
          <div class="flex items-center gap-2 border-b border-slate-100 px-4 py-2">
            <span class="inline-flex rounded px-2 py-0.5 text-xs font-medium" :class="STATUS_BADGE[doc.ingest_status] ?? 'bg-slate-100 text-slate-600'">
              {{ t(`docs.doc.status.${doc.ingest_status}`) }}
            </span>
            <span class="text-xs text-slate-500">{{ sourceLabel(doc.source_type) }} · {{ t('docs.doc.chunks', { n: doc.chunk_count }) }}</span>
            <div class="ml-auto">
              <button class="flex items-center gap-1 rounded-md bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100 disabled:opacity-50" :disabled="saving" @click="handleSave">
                <Loader2 v-if="saving" class="h-3 w-3 animate-spin" />
                <Save v-else class="h-3 w-3" />
                {{ t('docs.library.save') }}
              </button>
            </div>
          </div>

          <div class="min-h-0 flex-1 p-3">
            <MdEditor v-model="editContent" :toolbars-exclude="['github', 'prettier']" :language="editorLanguage()" input-box-width="38%" style="height: 100%" />
          </div>

          <div class="border-t border-slate-200 p-4">
            <h4 class="mb-2 text-xs font-medium uppercase text-slate-500">{{ t('docs.doc.meta.title') }}</h4>
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
    </div>
  </Teleport>
</template>
