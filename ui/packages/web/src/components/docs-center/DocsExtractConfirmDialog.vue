<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getLibraryExtractPreview, toast } from '@aihelms/shared'
import type { LibraryExtractPreview } from '@aihelms/shared'
import { Loader2, X, Wand2 } from 'lucide-vue-next'

interface Props {
  visible: boolean
  libraryName: string
}
const props = defineProps<Props>()
const emit = defineEmits<{ close: []; confirm: [] }>()
const { t } = useI18n()

const loading = ref(false)
const preview = ref<LibraryExtractPreview | null>(null)

// 打开时拉取预览：将提取（新增/变更）与将跳过（未变更）分组
watch(
  () => props.visible,
  async (v) => {
    if (!v) return
    preview.value = null
    loading.value = true
    try {
      preview.value = await getLibraryExtractPreview(props.libraryName)
    } catch (e) {
      toast.error((e as Error).message)
      emit('close')
    } finally {
      loading.value = false
    }
  },
)

const hasToDo = () => (preview.value?.to_extract?.length ?? 0) > 0
</script>

<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 p-4"
      @click.self="emit('close')"
    >
      <div class="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl">
        <div class="flex items-center justify-between border-b border-slate-100 p-5">
          <h3 class="text-base font-semibold text-slate-900">{{ t('docs.interfaces.previewTitle') }}</h3>
          <button class="text-slate-400 hover:text-slate-600" @click="emit('close')">
            <X class="h-5 w-5" />
          </button>
        </div>

        <div v-if="loading" class="flex items-center justify-center py-16">
          <Loader2 class="h-6 w-6 animate-spin text-slate-400" />
        </div>

        <div v-else-if="preview" class="flex-1 overflow-hidden p-5">
          <p v-if="!hasToDo()" class="py-8 text-center text-sm text-slate-500">
            {{ t('docs.interfaces.previewEmpty') }}
          </p>
          <div v-else class="grid grid-cols-2 gap-4">
            <div class="flex flex-col overflow-hidden rounded-lg border border-purple-200">
              <div class="border-b border-purple-100 bg-purple-50 px-3 py-2 text-xs font-semibold text-purple-700">
                {{ t('docs.interfaces.previewExtract') }} · {{ preview.to_extract.length }}
                <span class="ml-1 font-normal text-purple-500">
                  ({{ t('docs.interfaces.previewNew') }} {{ preview.summary.new }} · {{ t('docs.interfaces.previewChanged') }} {{ preview.summary.changed }})
                </span>
              </div>
              <div class="max-h-64 overflow-y-auto p-2">
                <div
                  v-for="item in preview.to_extract"
                  :key="item.id"
                  class="mb-1 flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50"
                >
                  <span
                    class="inline-flex shrink-0 rounded px-1.5 py-0.5 text-xs font-medium"
                    :class="item.reason === 'new' ? 'bg-blue-50 text-blue-700' : 'bg-amber-50 text-amber-700'"
                  >
                    {{ item.reason === 'new' ? t('docs.interfaces.previewNew') : t('docs.interfaces.previewChanged') }}
                  </span>
                  <span class="min-w-0 flex-1 truncate text-slate-700">{{ item.title }}</span>
                </div>
              </div>
            </div>
            <div class="flex flex-col overflow-hidden rounded-lg border border-slate-200">
              <div class="border-b border-slate-100 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600">
                {{ t('docs.interfaces.previewSkip') }} · {{ preview.skipped.length }}
              </div>
              <div class="max-h-64 overflow-y-auto p-2">
                <div
                  v-for="item in preview.skipped"
                  :key="item.id"
                  class="mb-1 flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50"
                >
                  <span class="inline-flex shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">{{ t('docs.interfaces.unchanged') }}</span>
                  <span class="min-w-0 flex-1 truncate text-slate-600">{{ item.title }}</span>
                </div>
                <p v-if="!preview.skipped.length" class="py-6 text-center text-xs text-slate-300">—</p>
              </div>
            </div>
          </div>
        </div>

        <div class="flex justify-end gap-2 border-t border-slate-100 p-4">
          <button class="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100" @click="emit('close')">
            {{ t('docs.library.cancel') }}
          </button>
          <button
            v-if="!loading && hasToDo()"
            class="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
            @click="emit('confirm')"
          >
            <Wand2 class="h-4 w-4" />
            {{ t('docs.interfaces.confirmExtract') }} ({{ preview?.to_extract.length ?? 0 }})
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
