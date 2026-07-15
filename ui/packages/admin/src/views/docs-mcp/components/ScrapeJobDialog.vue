<script setup lang="ts">
import { ref, watch } from 'vue'
import type { DocsMcpScrapeOptions } from '@aihelms/shared'
import { checkDocsMcpLibraryExists, findDocsMcpVersionsByUrl } from '@aihelms/shared'
import { X, ChevronDown, ChevronUp, Plus, Trash2, AlertTriangle } from 'lucide-vue-next'

interface Props {
  visible: boolean
  defaultUrl?: string
  defaultLibrary?: string
  defaultVersion?: string
}

interface Emits {
  close: []
  submit: [params: { url: string; library: string; version: string; options: DocsMcpScrapeOptions }]
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const url = ref(props.defaultUrl ?? '')
const library = ref(props.defaultLibrary ?? '')
const version = ref(props.defaultVersion ?? '')
const showAdvanced = ref(false)
const submitting = ref(false)
const maxPages = ref<number | undefined>(undefined)
const maxDepth = ref<number | undefined>(undefined)
const scope = ref<'subpages' | 'hostname' | 'domain'>('subpages')
const scrapeMode = ref<'fetch' | 'playwright' | 'auto'>('auto')
const includePatterns = ref<string[]>([])
const excludePatterns = ref<string[]>([])
const customHeaders = ref<{ key: string; value: string }[]>([])

// Debounce check state
const libraryCheckState = ref<'idle' | 'checking' | 'exists' | 'not_found'>('idle')
const urlCheckState = ref<'idle' | 'checking' | 'exists' | 'not_found'>('idle')
const urlCheckLibName = ref<string>('')
let checkTimer: ReturnType<typeof setTimeout> | null = null

function debounceCheck(): void {
  if (checkTimer) clearTimeout(checkTimer)
  checkTimer = setTimeout(doCheck, 600)
}

async function doCheck(): Promise<void> {
  const libVal = library.value.trim()
  const urlVal = url.value.trim()

  // Check library existence
  if (libVal) {
    libraryCheckState.value = 'checking'
    try {
      const res = await checkDocsMcpLibraryExists(libVal)
      libraryCheckState.value = res.exists ? 'exists' : 'not_found'
    } catch {
      libraryCheckState.value = 'idle'
    }
  } else {
    libraryCheckState.value = 'idle'
  }

  // Check URL already indexed
  if (urlVal) {
    urlCheckState.value = 'checking'
    try {
      const versions = await findDocsMcpVersionsByUrl(urlVal)
      if (versions.length > 0) {
        urlCheckState.value = 'exists'
        urlCheckLibName.value = versions[0].library_name ?? ''
      } else {
        urlCheckState.value = 'not_found'
      }
    } catch {
      urlCheckState.value = 'idle'
    }
  } else {
    urlCheckState.value = 'idle'
  }
}

// Watch inputs for debounced validation
watch([library, url], () => {
  debounceCheck()
})

// Reset state when dialog opens
watch(() => props.visible, (v) => {
  if (v) {
    libraryCheckState.value = 'idle'
    urlCheckState.value = 'idle'
    urlCheckLibName.value = ''
  }
})

const inputCls = 'w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500'
const smInputCls = 'w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none'

function addHeader(): void {
  customHeaders.value.push({ key: '', value: '' })
}

function removeHeader(index: number): void {
  customHeaders.value.splice(index, 1)
}

function onIncludePatternsInput(e: Event): void {
  includePatterns.value = (e.target as HTMLTextAreaElement).value.split('\n')
}

function onExcludePatternsInput(e: Event): void {
  excludePatterns.value = (e.target as HTMLTextAreaElement).value.split('\n')
}

function handleSubmit(): void {
  if (!url.value || !library.value) return
  submitting.value = true
  const options: DocsMcpScrapeOptions = {}
  if (maxPages.value) options.maxPages = maxPages.value
  if (maxDepth.value) options.maxDepth = maxDepth.value
  if (scope.value !== 'subpages') options.scope = scope.value
  if (scrapeMode.value !== 'auto') options.scrapeMode = scrapeMode.value
  const inc = includePatterns.value.filter((p) => p.trim())
  if (inc.length > 0) options.includePatterns = inc
  const exc = excludePatterns.value.filter((p) => p.trim())
  if (exc.length > 0) options.excludePatterns = exc
  const headers: Record<string, string> = {}
  for (const h of customHeaders.value) {
    if (h.key.trim()) headers[h.key.trim()] = h.value
  }
  if (Object.keys(headers).length > 0) options.headers = headers
  emit('submit', { url: url.value, library: library.value, version: version.value, options })
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
        <h3 class="mb-4 text-lg font-semibold text-gray-900">新建文档爬取任务</h3>
        <div class="space-y-4">
          <div>
            <label class="mb-1 block text-sm font-medium text-gray-700">文档 URL *</label>
            <input v-model="url" type="url" placeholder="https://docs.example.com" :class="inputCls" />
            <!-- URL already indexed warning -->
            <div v-if="urlCheckState === 'exists'" class="mt-1 flex items-center gap-1 text-xs text-amber-600">
              <AlertTriangle class="h-3 w-3" />
              该 URL 已在文档库「{{ urlCheckLibName }}」中索引
            </div>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block text-sm font-medium text-gray-700">库名 *</label>
              <input v-model="library" type="text" placeholder="my-docs" :class="inputCls" />
              <!-- Library exists warning -->
              <div v-if="libraryCheckState === 'exists'" class="mt-1 flex items-center gap-1 text-xs text-amber-600">
                <AlertTriangle class="h-3 w-3" />
                该文档库已存在，爬取将新增版本
              </div>
              <div v-else-if="libraryCheckState === 'not_found'" class="mt-1 text-xs text-emerald-600">
                新文档库
              </div>
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
              <div>
                <label class="mb-1 block text-xs text-gray-500">URL 包含模式 (每行一个)</label>
                <textarea :value="includePatterns.join('\n')" rows="2" placeholder="例如: /docs/.*\.md" :class="smInputCls" @input="onIncludePatternsInput" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-500">URL 排除模式 (每行一个)</label>
                <textarea :value="excludePatterns.join('\n')" rows="2" placeholder="例如: /api/.*" :class="smInputCls" @input="onExcludePatternsInput" />
              </div>
              <div>
                <div class="mb-1 flex items-center justify-between">
                  <label class="text-xs text-gray-500">自定义 Headers</label>
                  <button class="text-xs text-blue-600 hover:text-blue-700" @click="addHeader">
                    <Plus class="inline h-3 w-3" /> 添加
                  </button>
                </div>
                <div v-for="(h, i) in customHeaders" :key="i" class="mb-1 flex gap-2">
                  <input v-model="h.key" placeholder="Name" class="flex-1 rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none" />
                  <input v-model="h.value" placeholder="Value" class="flex-1 rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none" />
                  <button class="rounded p-1 text-gray-400 hover:text-red-500" @click="removeHeader(i)">
                    <Trash2 class="h-3 w-3" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="mt-6 flex justify-end gap-3">
          <button class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50" @click="emit('close')">取消</button>
          <button class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50" :disabled="!url || !library || submitting" @click="handleSubmit">提交任务</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
