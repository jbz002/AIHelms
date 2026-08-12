<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { uploadDocumentsBatch, toast } from '@aihelms/shared'
import { Loader2, X, Upload, FileText } from 'lucide-vue-next'

const DOCS_VERSION_RE = /^v?\d+\.\d+\.\d+$/

interface Props {
  visible: boolean
  libraryName: string
  defaultVersion: string
}
const props = defineProps<Props>()
const emit = defineEmits<{ close: []; uploaded: [version: string] }>()
const { t } = useI18n()

const version = ref(props.defaultVersion)
const files = ref<File[]>([])
const submitting = ref(false)

watch(
  () => props.visible,
  (v) => {
    if (v) {
      version.value = props.defaultVersion
      files.value = []
    }
  },
)

function handleFileChange(e: Event): void {
  const input = e.target as HTMLInputElement
  const picked = input.files ? Array.from(input.files) : []
  if (picked.length) {
    files.value = [...files.value, ...picked]
  }
  input.value = ''
}

function removeFile(index: number): void {
  files.value = files.value.filter((_, i) => i !== index)
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function submit(): Promise<void> {
  if (files.value.length === 0) {
    toast.error(t('docs.addVersion.noFile'))
    return
  }
  const v = version.value.trim()
  if (!v) {
    toast.error(t('docs.addVersion.versionRequired'))
    return
  }
  if (!DOCS_VERSION_RE.test(v)) {
    toast.error(t('docs.addVersion.versionInvalid'))
    return
  }
  submitting.value = true
  try {
    await uploadDocumentsBatch(props.libraryName, files.value, v, true)
    toast.success(t('docs.addVersion.success', { n: files.value.length }))
    emit('uploaded', v)
    emit('close')
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 p-4" @click.self="emit('close')">
      <div class="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-base font-semibold text-slate-900">{{ t('docs.addVersion.title') }}</h3>
          <button class="text-slate-400 hover:text-slate-600" @click="emit('close')">
            <X class="h-5 w-5" />
          </button>
        </div>

        <div class="space-y-3">
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.addVersion.library') }}</label>
            <div class="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-sm text-slate-600">{{ libraryName }}</div>
          </div>

          <div>
            <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.addVersion.version') }}</label>
            <input
              v-model="version"
              :placeholder="t('docs.addVersion.versionPlaceholder')"
              class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 text-sm focus:border-purple-400 focus:outline-none"
            />
            <p class="mt-1 text-xs text-slate-400">{{ t('docs.addVersion.versionHint') }}</p>
          </div>

          <div>
            <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.addVersion.file') }}</label>
            <label class="flex cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed border-slate-200 p-3 transition-colors hover:border-purple-300 hover:bg-purple-50/40">
              <div class="flex h-9 w-9 items-center justify-center rounded-full bg-slate-100">
                <Upload class="h-4 w-4 text-slate-500" />
              </div>
              <div class="flex-1 text-sm">
                <p class="text-slate-600">{{ t('docs.addVersion.pickFile') }}</p>
                <p class="mt-0.5 text-xs text-slate-400">{{ t('docs.addVersion.fileHint') }}</p>
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
                class="flex items-center gap-2 rounded-md border border-slate-200 px-2.5 py-1.5 text-sm"
              >
                <FileText class="h-3.5 w-3.5 shrink-0 text-purple-500" />
                <span class="min-w-0 flex-1 truncate text-slate-700">{{ f.name }}</span>
                <span class="shrink-0 text-xs text-slate-400">{{ formatFileSize(f.size) }}</span>
                <button
                  class="shrink-0 rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-red-500"
                  :disabled="submitting"
                  @click="removeFile(i)"
                >
                  <X class="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <button
            class="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100"
            @click="emit('close')"
          >{{ t('docs.library.cancel') }}</button>
          <button
            class="flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            :disabled="submitting || files.length === 0"
            @click="submit"
          >
            <Loader2 v-if="submitting" class="h-4 w-4 animate-spin" />
            {{ submitting ? t('docs.upload.submitting') : t('docs.addVersion.submit') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
