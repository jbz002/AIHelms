<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
import { ArrowLeft, Save, Loader2, Code2 } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const libraryName = computed(() => route.params.libraryName as string)
const docId = computed(() => Number(route.params.docId))

const doc = ref<Document | null>(null)
const loading = ref(false)
const saving = ref(false)
const editContent = ref('')

const statusConfig: Record<string, { label: string; cls: string }> = {
  pending: { label: '待入库', cls: 'bg-yellow-100 text-yellow-700' },
  ingesting: { label: '入库中', cls: 'bg-blue-100 text-blue-700' },
  ingested: { label: '已入库', cls: 'bg-green-100 text-green-700' },
  failed: { label: '失败', cls: 'bg-red-100 text-red-700' },
  duplicate: { label: '触发重复', cls: 'bg-gray-100 text-gray-500' },
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
  } catch (e) {
    toast.error((e as Error).message || '加载文档失败')
  } finally {
    loading.value = false
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function reingestInBackground(): Promise<void> {
  // 入库走 celery 异步：先派发任务，再轮询单文档状态直到终态
  try {
    await ingestDocument(docId.value)
  } catch (e) {
    toast.error((e as Error).message || '提交重新入库失败')
    return
  }
  for (let i = 0; i < 40; i++) {
    await sleep(1500)
    try {
      const d = await getDocument(docId.value)
      doc.value = d
      if (d.ingest_status === 'ingested') {
        toast.success('重新入库完成')
        void triggerExtract()
        return
      }
      if (d.ingest_status === 'failed') {
        toast.error(`重新入库失败：${d.error_message || '未知原因'}`)
        return
      }
    } catch {
      // 单次查询失败不中断轮询
    }
  }
}

async function triggerExtract(): Promise<void> {
  // 入库完成后自动重新提取接口（读平台 DB content，不依赖 docs-mcp 入库结果）
  try {
    await extractDocumentInterfaces(docId.value)
    toast.info('内容已变更，正在重新提取接口…')
  } catch (e) {
    // 409 进行中 / 400 内容为空 / 403 无权限 —— 仅 toast，不阻断主流程
    toast.error((e as Error).message || '提交接口提取失败')
    return
  }
  for (let i = 0; i < 60; i++) {
    await sleep(5000)
    try {
      const s = await getDocumentExtractStatus(docId.value)
      if (!s) return
      if (s.status === 'completed') {
        toast.success(`接口提取完成，共 ${s.endpoint_count} 个接口`)
        return
      }
      if (s.status === 'failed') {
        toast.error(`接口提取失败：${s.error_message || '未知原因'}`)
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
    toast.success('文档已保存')
    // 内容变更会重置 ingest_status=pending，自动后台重新入库（无需手动按钮）
    if (updated.ingest_status === 'pending') {
      toast.info('内容已变更，正在后台重新入库…')
      void reingestInBackground()
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
        <div class="ml-auto flex items-center gap-2">
          <button
            class="flex items-center gap-1 rounded-md bg-purple-50 px-3 py-1.5 text-xs font-medium text-purple-700 hover:bg-purple-100"
            @click="router.push({ name: 'DocumentInterfaces', params: { libraryName, docId } })"
          >
            <Code2 class="h-3 w-3" />
            接口
          </button>
          <button
            class="flex items-center gap-1 rounded-md bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100"
            :disabled="saving"
            @click="handleSave"
          >
            <Loader2 v-if="saving" class="h-3 w-3 animate-spin" />
            <Save v-else class="h-3 w-3" />
            保存
          </button>
        </div>
      </div>

      <div class="rounded-lg border border-gray-200 bg-white">
        <MdEditor v-model="editContent" language="zh-CN" :preview="true" :toolbars-exclude="['preview']" />
      </div>

      <div class="rounded-lg border border-gray-200 bg-white p-4">
        <h3 class="mb-2 text-xs font-medium uppercase text-gray-500">元数据</h3>
        <div class="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
          <div class="text-gray-500">知识库</div>
          <div class="text-gray-900">{{ doc.library }}</div>
          <div v-if="doc.version" class="text-gray-500">版本</div>
          <div v-if="doc.version" class="text-gray-900">{{ doc.version }}</div>
          <div class="text-gray-500">来源类型</div>
          <div class="text-gray-900">{{ doc.source_type === 'crawl' ? '爬虫' : '上传' }}</div>
          <div class="text-gray-500">内容哈希</div>
          <div class="font-mono text-xs text-gray-500">{{ doc.content_hash || '-' }}</div>
          <div v-if="doc.error_message" class="text-gray-500">错误信息</div>
          <div v-if="doc.error_message" class="text-sm text-red-600">{{ doc.error_message }}</div>
        </div>
      </div>
    </template>
  </div>
</template>
