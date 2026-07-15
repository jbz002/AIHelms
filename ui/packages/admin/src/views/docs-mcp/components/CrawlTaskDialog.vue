<script setup lang="ts">
import { ref, watch } from 'vue'
import type { DocsMcpScrapeOptions } from '@aihelms/shared'
import { X, ChevronDown, ChevronUp } from 'lucide-vue-next'

interface Props {
  visible: boolean
}

interface Emits {
  close: []
  submit: [params: { url: string; library: string; version: string; options: DocsMcpScrapeOptions }]
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const url = ref('')
const library = ref('')
const version = ref('')
const showAdvanced = ref(false)
const submitting = ref(false)
const maxPages = ref<number | undefined>(undefined)
const maxDepth = ref<number | undefined>(undefined)
const scope = ref<'subpages' | 'hostname' | 'domain'>('subpages')
const scrapeMode = ref<'fetch' | 'playwright' | 'auto'>('auto')

watch(() => props.visible, (v) => {
  if (v) {
    url.value = ''
    library.value = ''
    version.value = ''
    showAdvanced.value = false
    maxPages.value = undefined
    maxDepth.value = undefined
    scope.value = 'subpages'
    scrapeMode.value = 'auto'
  }
})

const inputCls = 'w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500'
const smInputCls = 'w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none'

function handleSubmit(): void {
  if (!url.value.trim() || !library.value.trim()) return
  submitting.value = true
  const options: DocsMcpScrapeOptions = {}
  if (maxPages.value) options.maxPages = maxPages.value
  if (maxDepth.value) options.maxDepth = maxDepth.value
  if (scope.value !== 'subpages') options.scope = scope.value
  if (scrapeMode.value !== 'auto') options.scrapeMode = scrapeMode.value
  emit('submit', {
    url: url.value.trim(),
    library: library.value.trim(),
    version: version.value.trim(),
    options,
  })
  submitting.value = false
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div class="relative w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <button class="absolute right-4 top-4 rounded-md p-1 text-gray-400 hover:bg-gray-100" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
        <h3 class="mb-4 text-lg font-semibold text-gray-900">新建爬取任务（不入库）</h3>
        <div class="space-y-4">
          <div>
            <label class="mb-1 block text-sm font-medium text-gray-700">文档 URL *</label>
            <input v-model="url" type="url" placeholder="https://docs.example.com" :class="inputCls" />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block text-sm font-medium text-gray-700">库名 *</label>
              <input v-model="library" type="text" placeholder="my-docs" :class="inputCls" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-gray-700">版本</label>
              <input v-model="version" type="text" placeholder="v1.0 (可选)" :class="inputCls" />
            </div>
          </div>
          <div class="rounded-md border border-gray-200">
            <button class="flex w-full items-center justify-between px-3 py-2 text-sm font-medium text-gray-700" @click="showAdvanced = !showAdvanced">
              高级选项
              <ChevronDown v-if="!showAdvanced" class="h-4 w-4" />
              <ChevronUp v-else class="h-4 w-4" />
            </button>
            <div v-if="showAdvanced" class="space-y-3 border-t border-gray-200 px-3 py-3">
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="mb-1 block text-xs text-gray-500">最大页数</label>
                  <input v-model.number="maxPages" type="number" placeholder="不限" :class="smInputCls" />
                </div>
                <div>
                  <label class="mb-1 block text-xs text-gray-500">最大深度</label>
                  <input v-model.number="maxDepth" type="number" placeholder="不限" :class="smInputCls" />
                </div>
              </div>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="mb-1 block text-xs text-gray-500">抓取范围</label>
                  <select v-model="scope" :class="smInputCls">
                    <option value="subpages">子页面</option>
                    <option value="hostname">同主机名</option>
                    <option value="domain">同域名</option>
                  </select>
                </div>
                <div>
                  <label class="mb-1 block text-xs text-gray-500">抓取模式</label>
                  <select v-model="scrapeMode" :class="smInputCls">
                    <option value="auto">自动</option>
                    <option value="fetch">简单抓取</option>
                    <option value="playwright">浏览器渲染</option>
                  </select>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="mt-6 flex justify-end gap-3">
          <button class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50" @click="emit('close')">取消</button>
          <button
            class="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!url.trim() || !library.trim() || submitting"
            @click="handleSubmit"
          >创建爬取任务</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
