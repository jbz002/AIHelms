<script setup lang="ts">
import { ref, watch } from 'vue'
import { fetchDocsMcpUrl, toast } from '@aihelms/shared'
import { Loader2, Globe, Copy, X } from 'lucide-vue-next'

interface Props {
  visible: boolean
}
const props = defineProps<Props>()
const emit = defineEmits<{
  close: []
}>()

const fetchUrl = ref('')
const fetchLoading = ref(false)
const fetchResult = ref<string | null>(null)

async function handleFetchUrl(): Promise<void> {
  const url = fetchUrl.value.trim()
  if (!url) return
  fetchLoading.value = true
  fetchResult.value = null
  try {
    const result = await fetchDocsMcpUrl(url)
    fetchResult.value = result.content
  } catch (e) {
    toast.error((e as Error).message || '抓取失败')
  } finally {
    fetchLoading.value = false
  }
}

function copyResult(): void {
  if (!fetchResult.value) return
  navigator.clipboard.writeText(fetchResult.value).then(() => {
    toast.success('已复制到剪贴板')
  })
}

// 抽屉关闭时清空状态，下次打开为干净输入
watch(
  () => props.visible,
  (v) => {
    if (!v) {
      fetchUrl.value = ''
      fetchResult.value = null
      fetchLoading.value = false
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-50">
      <div class="absolute inset-0 bg-black/30" @click="emit('close')" />
      <aside class="absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl">
      <div class="flex shrink-0 items-center justify-between border-b border-slate-200 px-5 py-3">
        <span class="text-sm font-semibold text-slate-900">抓取单页</span>
        <button
          class="flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-100"
          aria-label="关闭"
          @click="emit('close')"
        >
          <X class="h-4 w-4" />
        </button>
      </div>

      <div class="flex-1 overflow-y-auto px-5 py-4">
        <div class="flex items-center gap-3">
          <div class="relative flex-1">
            <Globe class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              v-model="fetchUrl"
              type="text"
              placeholder="输入 URL，抓取网页内容并转为 Markdown..."
              class="w-full rounded-md border border-gray-300 py-2.5 pl-10 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              @keyup.enter="handleFetchUrl"
            />
          </div>
          <button
            class="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            :disabled="!fetchUrl.trim() || fetchLoading"
            @click="handleFetchUrl"
          >
            <Loader2 v-if="fetchLoading" class="h-4 w-4 animate-spin" />
            <Globe v-else class="h-4 w-4" />
            抓取
          </button>
        </div>

        <div v-if="fetchResult !== null" class="mt-4">
          <div class="mb-2 flex items-center justify-between">
            <span class="text-sm text-gray-500">抓取结果（{{ fetchResult.length }} 字符）</span>
            <button
              class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
              @click="copyResult"
            >
              <Copy class="h-3 w-3" />
              复制
            </button>
          </div>
          <pre class="max-h-[60vh] overflow-auto rounded-md bg-gray-50 p-3 text-xs leading-relaxed text-gray-700 whitespace-pre-wrap break-words">{{ fetchResult }}</pre>
        </div>
      </div>
      </aside>
    </div>
  </Teleport>
</template>
