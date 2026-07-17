<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MdEditor } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import type { Document } from '@aihelms/shared'
import { getDocument, updateDocument, toast } from '@aihelms/shared'
import { ArrowLeft, Save, X, Loader2, Pencil } from 'lucide-vue-next'
import { MarkdownRenderer } from '@aihelms/shared'

const route = useRoute()
const router = useRouter()
const libraryName = computed(() => route.params.libraryName as string)
const docId = computed(() => Number(route.params.docId))
const startInEdit = computed(() => route.query.edit === '1')

const doc = ref<Document | null>(null)
const loading = ref(false)
const saving = ref(false)
const isEditing = ref(false)
const editContent = ref('')

const statusConfig: Record<string, { label: string; cls: string }> = {
  pending: { label: '待入库', cls: 'bg-yellow-100 text-yellow-700' },
  ingesting: { label: '入库中', cls: 'bg-blue-100 text-blue-700' },
  ingested: { label: '已入库', cls: 'bg-green-100 text-green-700' },
  failed: { label: '失败', cls: 'bg-red-100 text-red-700' },
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 19)
}

async function loadDocument(): Promise<void> {
  loading.value = true
  try {
    doc.value = await getDocument(docId.value)
    editContent.value = doc.value?.content ?? ''
    if (startInEdit.value) isEditing.value = true
  } catch (e) {
    toast.error((e as Error).message || '加载文档失败')
  } finally {
    loading.value = false
  }
}

function handleEdit(): void {
  if (!doc.value) return
  editContent.value = doc.value.content
  isEditing.value = true
}

function handleCancel(): void {
  isEditing.value = false
  editContent.value = doc.value?.content ?? ''
}

async function handleSave(): Promise<void> {
  if (!doc.value || saving.value) return
  saving.value = true
  const prevStatus = doc.value.ingest_status
  try {
    const updated = await updateDocument(docId.value, { content: editContent.value })
    doc.value = updated
    isEditing.value = false
    toast.success('文档已保存')
    if (prevStatus === 'ingested' && updated.ingest_status === 'pending') {
      toast.warning('内容已变更，需要重新入库')
    }
  } catch (e) {
    toast.error((e as Error).message || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadDocument)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-3">
      <button
        class="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        @click="router.push({ name: 'DocumentList', params: { libraryName } })"
      >
        <ArrowLeft class="h-4 w-4" />
      </button>
      <h2 class="text-lg font-semibold text-gray-900 truncate">{{ doc?.title || `文档 #${docId}` }}</h2>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-20">
      <Loader2 class="h-6 w-6 animate-spin text-gray-400" />
    </div>

    <template v-else-if="doc">
      <div class="flex items-center gap-2">
        <span :class="['rounded-full px-2 py-0.5 text-xs font-medium', statusConfig[doc.ingest_status]?.cls ?? 'bg-gray-100 text-gray-700']">
          {{ statusConfig[doc.ingest_status]?.label ?? doc.ingest_status }}
        </span>
        <span class="text-xs text-gray-500">
          {{ doc.source_type === 'crawl' ? '爬虫' : '上传' }}
          · {{ doc.chunk_count }} 分块
        </span>
        <span class="text-xs text-gray-400">{{ fmtTime(doc.updated_at) }}</span>
        <div class="ml-auto">
          <button
            v-if="!isEditing"
            class="flex items-center gap-1 rounded-md bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
            @click="handleEdit"
          >
            <Pencil class="h-3 w-3" />
            编辑
          </button>
          <template v-else>
            <button
              class="mr-2 flex items-center gap-1 rounded-md bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100"
              :disabled="saving"
              @click="handleSave"
            >
              <Loader2 v-if="saving" class="h-3 w-3 animate-spin" />
              <Save v-else class="h-3 w-3" />
              保存
            </button>
            <button
              class="flex items-center gap-1 rounded-md bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-200"
              :disabled="saving"
              @click="handleCancel"
            >
              <X class="h-3 w-3" />
              取消
            </button>
          </template>
        </div>
      </div>

      <div v-if="isEditing" class="rounded-lg border border-gray-200 bg-white">
        <MdEditor v-model="editContent" language="zh-CN" :preview="true" />
      </div>

      <div v-else class="rounded-lg border border-gray-200 bg-white p-6">
        <MarkdownRenderer v-if="doc.content" :content="doc.content" />
        <p v-else class="text-sm text-gray-400">文档内容为空</p>
      </div>

      <div class="rounded-lg border border-gray-200 bg-white p-4">
        <h3 class="mb-2 text-xs font-medium uppercase text-gray-500">元数据</h3>
        <div class="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
          <div class="text-gray-500">知识库</div>
          <div class="text-gray-900">{{ doc.library }}</div>
          <div class="text-gray-500">版本</div>
          <div class="text-gray-900">{{ doc.version || '-' }}</div>
          <div class="text-gray-500">来源类型</div>
          <div class="text-gray-900">{{ doc.source_type }}</div>
          <div class="text-gray-500">内容哈希</div>
          <div class="font-mono text-xs text-gray-500">{{ doc.content_hash || '-' }}</div>
          <div v-if="doc.error_message" class="text-gray-500">错误信息</div>
          <div v-if="doc.error_message" class="text-sm text-red-600">{{ doc.error_message }}</div>
        </div>
      </div>
    </template>
  </div>
</template>
