<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { uploadDocument, toast } from '@aihelms/shared'
import { Loader2, X } from 'lucide-vue-next'

interface Props {
  visible: boolean
  libraryName: string
  version: string
  lockVersion?: boolean
}
const props = defineProps<Props>()
const emit = defineEmits<{ close: []; uploaded: [version: string] }>()
const { t } = useI18n()

const DOCS_VERSION_RE = /^v?\d+\.\d+\.\d+$/
const autoIngest = ref(true)
const file = ref<File | null>(null)
const localVersion = ref(props.version)
const submitting = ref(false)

watch(
  () => props.visible,
  (v) => {
    if (v) {
      autoIngest.value = true
      file.value = null
      localVersion.value = props.version
    }
  },
)

function onFileChange(e: Event): void {
  const target = e.target as HTMLInputElement
  file.value = target.files && target.files.length ? target.files[0] : null
}

async function submit(): Promise<void> {
  if (!file.value) {
    toast.error(t('docs.upload.noFile'))
    return
  }
  const actualVersion = props.lockVersion ? props.version : localVersion.value.trim()
  if (!props.lockVersion) {
    if (!actualVersion) {
      toast.error(t('docs.addVersion.versionRequired'))
      return
    }
    if (!DOCS_VERSION_RE.test(actualVersion)) {
      toast.error(t('docs.addVersion.versionInvalid'))
      return
    }
  }
  submitting.value = true
  try {
    await uploadDocument(props.libraryName, file.value, actualVersion, autoIngest.value)
    toast.success(autoIngest.value ? t('docs.upload.success') : t('docs.upload.successExtract'))
    emit('uploaded', actualVersion)
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
      <div class="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-base font-semibold text-slate-900">{{ t('docs.upload.title') }}</h3>
          <button class="text-slate-400 hover:text-slate-600" @click="emit('close')">
            <X class="h-5 w-5" />
          </button>
        </div>

        <div class="space-y-3">
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.upload.library') }}</label>
              <div class="truncate rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-sm text-slate-600">
                {{ libraryName }}
              </div>
            </div>
            <div>
              <label class="mb-1 block text-xs font-medium text-slate-500">
                {{ t('docs.addVersion.version') }}<span v-if="!lockVersion" class="text-red-500">*</span>
              </label>
              <input
                v-if="!lockVersion"
                v-model="localVersion"
                type="text"
                :placeholder="t('docs.addVersion.versionPlaceholder')"
                class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 text-sm focus:border-purple-400 focus:outline-none"
              />
              <div v-else class="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-sm text-slate-600">
                {{ version === 'latest' ? t('docs.version.latest') : version }}
              </div>
            </div>
          </div>

          <div>
            <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.upload.file') }}</label>
            <input
              type="file"
              class="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-purple-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-purple-700 hover:file:bg-purple-100"
              @change="onFileChange"
            />
          </div>

          <label class="flex items-center gap-2 text-sm text-slate-600">
            <input v-model="autoIngest" type="checkbox" class="rounded border-slate-300 text-purple-600 focus:ring-purple-500" />
            {{ t('docs.upload.autoIngest') }}
          </label>
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <button
            class="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100"
            @click="emit('close')"
          >{{ t('docs.library.cancel') }}</button>
          <button
            class="flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            :disabled="submitting"
            @click="submit"
          >
            <Loader2 v-if="submitting" class="h-4 w-4 animate-spin" />
            {{ submitting ? t('docs.upload.submitting') : t('docs.upload.submit') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
