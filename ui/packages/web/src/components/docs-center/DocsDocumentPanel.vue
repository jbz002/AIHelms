<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Document } from '@aihelms/shared'
import { getDocuments, extractDocumentInterfaces, getDocumentExtractStatus, deleteDocument, toast } from '@aihelms/shared'
import { Loader2, Upload, Wand2, FileText, Trash2 } from 'lucide-vue-next'
import DocsUploadDialog from './DocsUploadDialog.vue'

interface Props {
  libraryName: string
  canManage: boolean
}
const props = defineProps<Props>()
const { t } = useI18n()

const loading = ref(false)
const documents = ref<Document[]>([])
const uploadVisible = ref(false)
const extracting = ref<Set<number>>(new Set())
const extractTimers = new Map<number, number>()

const STATUS_BADGE: Record<string, string> = {
  pending: 'bg-slate-100 text-slate-600',
  ingesting: 'bg-blue-50 text-blue-700',
  ingested: 'bg-green-50 text-green-700',
  failed: 'bg-red-50 text-red-700',
  duplicate: 'bg-amber-50 text-amber-700',
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const res = await getDocuments(props.libraryName, undefined, undefined, 1, 100)
    documents.value = res.items
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    loading.value = false
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
  load()
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
    load()
  },
)

onMounted(load)
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-2">
      <h2 class="text-base font-semibold text-slate-900">{{ t('docs.doc.title') }} · {{ libraryName }}</h2>
      <div v-if="canManage" class="ml-auto">
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700"
          @click="uploadVisible = true"
        >
          <Upload class="h-4 w-4" />
          {{ t('docs.doc.upload') }}
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
            <th class="px-3 py-2 text-left font-medium">{{ t('docs.doc.col.version') }}</th>
            <th class="px-3 py-2 text-left font-medium">{{ t('docs.doc.col.status') }}</th>
            <th class="px-3 py-2 text-right font-medium">{{ t('docs.doc.col.actions') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-for="doc in documents" :key="doc.id" class="hover:bg-slate-50">
            <td class="max-w-xs truncate px-3 py-2 text-slate-700">{{ doc.title || doc.source_id }}</td>
            <td class="px-3 py-2 text-slate-500">{{ doc.source_type }}</td>
            <td class="px-3 py-2 font-mono text-xs text-slate-500">{{ doc.version }}</td>
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

    <DocsUploadDialog :visible="uploadVisible" :library-name="libraryName" @uploaded="onUploaded" @close="uploadVisible = false" />
  </div>
</template>
