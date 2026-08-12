<script setup lang="ts">
import { ref } from 'vue'
import { uploadDocumentsBatch, toast } from '@aihelms/shared'
import { X, Upload, Loader2, FileText } from 'lucide-vue-next'

const DOCS_VERSION_RE = /^v?\d+\.\d+\.\d+$/

interface Props {
  defaultLibrary: string
  defaultVersion?: string
}

interface Emits {
  close: []
  uploaded: []
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const library = ref(props.defaultLibrary)
const version = ref(props.defaultVersion ?? '')
const files = ref<File[]>([])
const uploading = ref(false)
const submitError = ref<string | null>(null)

function handleFileChange(e: Event): void {
  const input = e.target as HTMLInputElement
  const picked = input.files ? Array.from(input.files) : []
  if (picked.length) {
    files.value = [...files.value, ...picked]
  }
  submitError.value = null
  input.value = ''
}

function removeFile(index: number): void {
  files.value = files.value.filter((_, i) => i !== index)
}

async function handleSubmit(): Promise<void> {
  if (!library.value.trim() || files.value.length === 0) return
  const versionInput = version.value.trim()
  if (!versionInput) {
    toast.error('请填写版本号（如 1.0.0）')
    return
  }
  if (!DOCS_VERSION_RE.test(versionInput)) {
    toast.error('版本号格式无效，请填写完整版本号（如 1.0.0）')
    return
  }

  uploading.value = true
  submitError.value = null

  try {
    const count = files.value.length
    await uploadDocumentsBatch(
      library.value.trim(),
      files.value,
      versionInput,
      true,
    )
    toast.success(`已提交 ${count} 个文件到后台处理`)
    emit('uploaded')
    resetAndClose()
  } catch (e) {
    submitError.value = (e as Error).message || '上传失败'
  } finally {
    uploading.value = false
  }
}

function resetAndClose(): void {
  files.value = []
  submitError.value = null
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
  <div class="space-y-4">
    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="mb-1 block text-sm font-medium text-gray-700">文档库 *</label>
        <input
          :value="library"
          type="text"
          disabled
          :class="inputCls"
          class="disabled:bg-slate-50 disabled:text-slate-400"
        />
      </div>
      <div>
        <label class="mb-1 block text-sm font-medium text-gray-700">版本 *</label>
        <input
          v-model="version"
          type="text"
          placeholder="填写新版本号，如 1.0.0"
          :class="inputCls"
        />
      </div>
    </div>

    <div>
      <label class="mb-1 block text-sm font-medium text-gray-700">选择文件 *（支持多选）</label>
      <label class="flex cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed border-gray-300 p-4 transition-colors hover:border-blue-400 hover:bg-blue-50/50">
        <div class="flex h-10 w-10 items-center justify-center rounded-full bg-gray-100">
          <Upload class="h-5 w-5 text-gray-500" />
        </div>
        <div class="flex-1 text-sm">
          <p class="text-gray-500">点击选择文件，可多选</p>
          <p class="mt-0.5 text-xs text-gray-400">支持 Markdown、TXT、CSV、JSON、YAML、HTML、代码文件、PDF、Office 文档、图片</p>
        </div>
        <input
          type="file"
          multiple
          class="hidden"
          accept=".md,.markdown,.txt,.csv,.json,.yaml,.yml,.xml,.html,.htm,.log,.py,.js,.ts,.sql,.sh,.rst,.toml,.ini,.cfg,.pdf,.docx,.xlsx,.pptx,.odt,.ods,.odp,.epub,.png,.jpg,.jpeg,.tiff,.bmp,.webp"
          @change="handleFileChange"
        />
      </label>

      <div v-if="files.length > 0" class="mt-2 space-y-1">
        <div
          v-for="(f, i) in files"
          :key="`${f.name}-${f.size}-${i}`"
          class="flex items-center gap-2 rounded-md border border-gray-200 px-3 py-1.5 text-sm"
        >
          <FileText class="h-4 w-4 shrink-0 text-blue-500" />
          <span class="min-w-0 flex-1 truncate text-gray-900">{{ f.name }}</span>
          <span class="shrink-0 text-xs text-gray-400">{{ formatFileSize(f.size) }}</span>
          <button
            class="shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-red-500"
            :disabled="uploading"
            title="移除"
            @click="removeFile(i)"
          >
            <X class="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>

    <div v-if="submitError" class="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
      {{ submitError }}
    </div>
  </div>

  <div class="mt-6 flex justify-end gap-3">
    <button
      class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
      @click="resetAndClose"
    >
      取消
    </button>
    <button
      class="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
      :disabled="!library.trim() || !version.trim() || files.length === 0 || uploading"
      @click="handleSubmit"
    >
      <Loader2 v-if="uploading" class="h-4 w-4 animate-spin" />
      <Upload v-else class="h-4 w-4" />
      {{ uploading ? '提交中...' : `上传${files.length > 0 ? ` ${files.length} 个文件` : ''}` }}
    </button>
  </div>
</template>
