<script setup lang="ts">
import { ref, watch } from 'vue'
import { uploadDocument, toast } from '@aihelms/shared'
import type { DocUploadRecord } from '@aihelms/shared'
import { X, Upload, Loader2, FileText, CheckCircle2, AlertCircle } from 'lucide-vue-next'

type IngestMode = 'direct' | 'extract-only'

interface Props {
  visible: boolean
  defaultLibrary?: string
}

interface Emits {
  close: []
  uploaded: [record: DocUploadRecord]
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const library = ref(props.defaultLibrary ?? '')
const version = ref('')
const file = ref<File | null>(null)
const ingestMode = ref<IngestMode>('direct')
const uploading = ref(false)
const uploadResult = ref<DocUploadRecord | null>(null)
const uploadError = ref<string | null>(null)

watch(() => props.visible, (v) => {
  if (v) {
    ingestMode.value = 'direct'
  }
})

function handleFileChange(e: Event): void {
  const input = e.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
  uploadResult.value = null
  uploadError.value = null
}

async function handleSubmit(): Promise<void> {
  if (!library.value.trim() || !file.value) return

  uploading.value = true
  uploadResult.value = null
  uploadError.value = null

  try {
    const record = await uploadDocument(
      library.value.trim(),
      file.value,
      version.value.trim() || undefined,
      ingestMode.value === 'direct',
    )
    uploadResult.value = record
    if (record.status === 'failed') {
      uploadError.value = record.error_message || '处理失败'
    } else if (record.status === 'completed') {
      toast.success(`入库成功，已生成 ${record.chunk_count} 个文档块`)
      emit('uploaded', record)
    } else {
      toast.success('文档提取成功，可稍后手动入库')
      emit('uploaded', record)
    }
  } catch (e) {
    uploadError.value = (e as Error).message || '上传失败'
  } finally {
    uploading.value = false
  }
}

function resetAndClose(): void {
  file.value = null
  uploadResult.value = null
  uploadError.value = null
  emit('close')
}

const inputCls = 'w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500'

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div class="relative w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <button
          class="absolute right-4 top-4 rounded-md p-1 text-gray-400 hover:bg-gray-100"
          @click="resetAndClose"
        >
          <X class="h-5 w-5" />
        </button>

        <h3 class="mb-4 text-lg font-semibold text-gray-900">上传文档</h3>

        <div class="space-y-4">
          <!-- 入库模式 -->
          <div class="flex items-center gap-6 rounded-md border border-gray-200 px-4 py-3">
            <label class="flex cursor-pointer items-center gap-2">
              <input v-model="ingestMode" type="radio" name="uploadIngestMode" value="direct" class="accent-blue-600" />
              <div>
                <span class="text-sm font-medium text-gray-900">直接入库</span>
                <p class="text-xs text-gray-500">提取后自动入库，可立即搜索</p>
              </div>
            </label>
            <label class="flex cursor-pointer items-center gap-2">
              <input v-model="ingestMode" type="radio" name="uploadIngestMode" value="extract-only" class="accent-emerald-600" />
              <div>
                <span class="text-sm font-medium text-gray-900">仅提取</span>
                <p class="text-xs text-gray-500">先提取内容，可预览后手动入库</p>
              </div>
            </label>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block text-sm font-medium text-gray-700">文档库 *</label>
              <input v-model="library" type="text" placeholder="my-docs" :class="inputCls" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-gray-700">版本</label>
              <input v-model="version" type="text" placeholder="v1.0 (可选)" :class="inputCls" />
            </div>
          </div>

          <div>
            <label class="mb-1 block text-sm font-medium text-gray-700">选择文件 *</label>
            <label class="flex cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed border-gray-300 p-6 transition-colors hover:border-blue-400 hover:bg-blue-50/50">
              <div class="flex h-10 w-10 items-center justify-center rounded-full bg-gray-100">
                <Upload class="h-5 w-5 text-gray-500" />
              </div>
              <div class="flex-1 text-sm">
                <template v-if="file">
                  <div class="flex items-center gap-2">
                    <FileText class="h-4 w-4 text-blue-500" />
                    <span class="font-medium text-gray-900">{{ file.name }}</span>
                    <span class="text-gray-400">{{ formatFileSize(file.size) }}</span>
                  </div>
                </template>
                <template v-else>
                  <p class="text-gray-500">点击选择文件或拖拽到此处</p>
                  <p class="text-xs text-gray-400 mt-0.5">支持 Markdown、TXT、CSV、JSON、YAML、HTML、代码文件、PDF、Office 文档、图片</p>
                </template>
              </div>
              <input
                type="file"
                class="hidden"
                accept=".md,.markdown,.txt,.csv,.json,.yaml,.yml,.xml,.html,.htm,.log,.py,.js,.ts,.sql,.sh,.rst,.toml,.ini,.cfg,.pdf,.docx,.xlsx,.pptx,.odt,.ods,.odp,.epub,.png,.jpg,.jpeg,.tiff,.bmp,.webp"
                @change="handleFileChange"
              />
            </label>
          </div>

          <!-- Upload result -->
          <div v-if="uploadResult" class="rounded-lg border p-3" :class="uploadError ? 'border-red-200 bg-red-50' : 'border-green-200 bg-green-50'">
            <div class="flex items-center gap-2 text-sm">
              <CheckCircle2 v-if="!uploadError" class="h-4 w-4 text-green-600" />
              <AlertCircle v-else class="h-4 w-4 text-red-600" />
              <span :class="uploadError ? 'text-red-700' : 'text-green-700'">
                {{ uploadError || (uploadResult.status === 'completed' ? `入库成功，共 ${uploadResult.chunk_count} 个文档块` : '提取成功') }}
              </span>
            </div>
          </div>
          <div v-else-if="uploadError" class="rounded-lg border border-red-200 bg-red-50 p-3">
            <div class="flex items-center gap-2 text-sm text-red-700">
              <AlertCircle class="h-4 w-4" />
              {{ uploadError }}
            </div>
          </div>
        </div>

        <div class="mt-6 flex justify-end gap-3">
          <button
            class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            @click="resetAndClose"
          >
            关闭
          </button>
          <button
            class="inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            :class="ingestMode === 'extract-only' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-blue-600 hover:bg-blue-700'"
            :disabled="!library.trim() || !file || uploading"
            @click="handleSubmit"
          >
            <Loader2 v-if="uploading" class="h-4 w-4 animate-spin" />
            <Upload v-else class="h-4 w-4" />
            {{ uploading ? '处理中...' : (ingestMode === 'extract-only' ? '提取' : '上传入库') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
