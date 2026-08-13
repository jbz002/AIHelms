<script setup lang="ts">
import { ref, watch } from 'vue'
import { getLibraryExtractPreview, toast } from '@aihelms/shared'
import type { LibraryExtractPreview } from '@aihelms/shared'
import { Loader2, X, Wand2 } from 'lucide-vue-next'

interface Props {
  visible: boolean
  libraryName: string
}
const props = defineProps<Props>()
const emit = defineEmits<{ close: []; confirm: [] }>()

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
      toast.error((e as Error).message || '加载预览失败')
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
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      @click.self="emit('close')"
    >
      <div class="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl">
        <div class="flex items-center justify-between border-b border-gray-200 p-5">
          <h3 class="text-lg font-semibold text-gray-900">确认提取接口</h3>
          <button class="rounded-md p-1 text-gray-400 hover:bg-gray-100" @click="emit('close')">
            <X class="h-5 w-5" />
          </button>
        </div>

        <div v-if="loading" class="flex items-center justify-center py-16">
          <Loader2 class="h-6 w-6 animate-spin text-gray-400" />
        </div>

        <div v-else-if="preview" class="flex-1 overflow-hidden p-5">
          <p v-if="!hasToDo()" class="py-8 text-center text-sm text-gray-500">
            所有文档接口已是最新，无需提取
          </p>
          <div v-else class="grid grid-cols-2 gap-4">
            <div class="flex flex-col overflow-hidden rounded-lg border border-purple-200">
              <div class="border-b border-purple-100 bg-purple-50 px-3 py-2 text-xs font-semibold text-purple-700">
                将提取 · {{ preview.to_extract.length }}
                <span class="ml-1 font-normal text-purple-500">
                  (新增 {{ preview.summary.new }} · 变更 {{ preview.summary.changed }})
                </span>
              </div>
              <div class="max-h-64 overflow-y-auto p-2">
                <div
                  v-for="item in preview.to_extract"
                  :key="item.id"
                  class="mb-1 flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-gray-50"
                >
                  <span
                    class="inline-flex shrink-0 rounded px-1.5 py-0.5 text-xs font-medium"
                    :class="item.reason === 'new' ? 'bg-blue-50 text-blue-700' : 'bg-amber-50 text-amber-700'"
                  >
                    {{ item.reason === 'new' ? '新增' : '变更' }}
                  </span>
                  <span class="min-w-0 flex-1 truncate text-gray-700">{{ item.title }}</span>
                </div>
              </div>
            </div>
            <div class="flex flex-col overflow-hidden rounded-lg border border-gray-200">
              <div class="border-b border-gray-100 bg-gray-50 px-3 py-2 text-xs font-semibold text-gray-600">
                将跳过 · {{ preview.skipped.length }}
              </div>
              <div class="max-h-64 overflow-y-auto p-2">
                <div
                  v-for="item in preview.skipped"
                  :key="item.id"
                  class="mb-1 flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-gray-50"
                >
                  <span class="inline-flex shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">未变更</span>
                  <span class="min-w-0 flex-1 truncate text-gray-600">{{ item.title }}</span>
                </div>
                <p v-if="!preview.skipped.length" class="py-6 text-center text-xs text-gray-300">—</p>
              </div>
            </div>
          </div>
        </div>

        <div class="flex justify-end gap-3 border-t border-gray-200 p-4">
          <button
            class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            @click="emit('close')"
          >
            取消
          </button>
          <button
            v-if="!loading && hasToDo()"
            class="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
            @click="emit('confirm')"
          >
            <Wand2 class="h-4 w-4" />
            确认提取 ({{ preview?.to_extract.length ?? 0 }})
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
