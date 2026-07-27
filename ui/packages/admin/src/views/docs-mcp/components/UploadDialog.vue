<script setup lang="ts">
import { ref, watch } from 'vue'
import { uploadDocumentsBatch, toast } from '@aihelms/shared'
import { X, Upload, Loader2, FileText } from 'lucide-vue-next'

const DOCS_VERSION_RE = /^v?\d+\.\d+\.\d+$/

type IngestMode = 'direct' | 'extract-only'

interface Props {
  visible: boolean
  defaultLibrary?: string
  defaultVersion?: string
  lockLibrary?: boolean
  lockVersion?: boolean
}

interface Emits {
  close: []
  uploaded: []
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const library = ref(props.defaultLibrary ?? '')
const version = ref(props.defaultVersion ?? '')
const files = ref<File[]>([])
const ingestMode = ref<IngestMode>('direct')
const uploading = ref(false)
const submitError = ref<string | null>(null)

watch(() => props.visible, (v) => {
  if (v) {
    if (props.lockLibrary) {
      library.value = props.defaultLibrary ?? ''
    }
    if (props.lockVersion) {
      version.value = props.defaultVersion ?? ''
    }
    ingestMode.value = 'direct'
  }
})

function handleFileChange(e: Event): void {
  const input = e.target as HTMLInputElement
  const picked = input.files ? Array.from(input.files) : []
  if (picked.length) {
    files.value = [...files.value, ...picked]
  }
  submitError.value = null
  // 清空 input.value，允许再次选择同名文件
  input.value = ''
}

function removeFile(index: number): void {
  files.value = files.value.filter((_, i) => i !== index)
}

async function handleSubmit(): Promise<void> {
  if (!library.value.trim() || files.value.length === 0) return
  const versionInput = version.value.trim()
  // lockVersion 模式下 version 来自父级（可能 "latest" 哨兵，后端解析），跳过格式校验
  if (!props.lockVersion && versionInput && !DOCS_VERSION_RE.test(versionInput)) {
    toast.error('版本号格式无效，请留空或填写完整版本号（如 1.0.0）')
    return
  }

  uploading.value = true
  submitError.value = null

  try {
    const count = files.value.length
    await uploadDocumentsBatch(
      library.value.trim(),
      files.value,
      version.value.trim() || undefined,
      ingestMode.value === 'direct',
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
              <input
                v-model="library"
                type="text"
                placeholder="my-docs"
                :disabled="lockLibrary"
                :class="inputCls"
                class="disabled:bg-slate-50 disabled:text-slate-400"
              />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-gray-700">版本</label>
              <input
                v-model="version"
                type="text"
                :placeholder="lockVersion && !version ? '默认版本' : '留空或完整版本号，如 1.0.0'"
                :disabled="lockVersion"
                :class="inputCls"
                class="disabled:bg-slate-50 disabled:text-slate-400"
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
            关闭
          </button>
          <button
            class="inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            :class="ingestMode === 'extract-only' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-blue-600 hover:bg-blue-700'"
            :disabled="!library.trim() || files.length === 0 || uploading"
            @click="handleSubmit"
          >
            <Loader2 v-if="uploading" class="h-4 w-4 animate-spin" />
            <Upload v-else class="h-4 w-4" />
            {{ uploading ? '提交中...' : `上传${files.length > 0 ? ` ${files.length} 个文件` : ''}` }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
