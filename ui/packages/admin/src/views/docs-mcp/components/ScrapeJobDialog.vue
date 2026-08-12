<script setup lang="ts">
import { ref, watch } from 'vue'
import type { DocsMcpScrapeOptions } from '@aihelms/shared'
import { checkDocsMcpLibraryExists, findDocsMcpVersionsByUrl, toast } from '@aihelms/shared'
import { X, ChevronDown, ChevronUp, Plus, Trash2, AlertTriangle } from 'lucide-vue-next'

const DOCS_VERSION_RE = /^v?\d+\.\d+\.\d+$/

interface Props {
  visible: boolean
  defaultUrl?: string
  defaultLibrary?: string
  defaultVersion?: string
  lockLibrary?: boolean
  lockVersion?: boolean
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
const maxPages = ref(1000)
const maxDepth = ref(3)
const scope = ref<'subpages' | 'hostname' | 'domain'>('subpages')
const scrapeMode = ref<'fetch' | 'playwright' | 'auto'>('auto')
const includePatterns = ref<string[]>([])
const DEFAULT_EXCLUDE_PATTERNS = [
  '**/CHANGELOG.md',
  '**/CHANGELOG/**',
  '**/LICENSE',
  '**/LICENSE/**',
  '**/*.lock',
  '**/package-lock.json',
  '**/yarn.lock',
  '**/pnpm-lock.yaml',
  '**/go.sum',
  '**/*.min.js',
  '**/*.min.css',
  '**/*.map',
  '**/*.d.ts',
  '**/.DS_Store',
  '**/Thumbs.db',
  '**/archive/**',
  '**/archived/**',
  '**/deprecated/**',
  '**/legacy/**',
  '**/old/**',
  '**/test/**',
  '**/tests/**',
  '**/__tests__/**',
  '**/spec/**',
  '**/dist/**',
  '**/build/**',
  '**/out/**',
  '**/target/**',
  '**/.next/**',
  '**/.nuxt/**',
  '**/.vscode/**',
  '**/.idea/**',
  '**/docs/old/**',
]

const excludePatterns = ref<string[]>([...DEFAULT_EXCLUDE_PATTERNS])
const customHeaders = ref<{ key: string; value: string }[]>([])
const followRedirects = ref(true)
const ignoreErrors = ref(true)

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

watch([library, url], () => {
  debounceCheck()
})

watch(() => props.visible, (v) => {
  if (v) {
    if (props.lockLibrary) {
      library.value = props.defaultLibrary ?? ''
    }
    if (props.lockVersion) {
      version.value = props.defaultVersion ?? ''
    } else {
      version.value = props.defaultVersion?.trim() || '1.0.0'
    }
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
  const versionInput = version.value.trim()
  // lockVersion 模式下 version 来自父级（可能 "latest" 哨兵，后端解析），跳过必填与格式校验
  if (!props.lockVersion && !versionInput) {
    toast.error('请填写版本号（如 1.0.0）')
    return
  }
  if (!props.lockVersion && versionInput && !DOCS_VERSION_RE.test(versionInput)) {
    toast.error('版本号格式无效，请填写完整版本号（如 1.0.0）')
    return
  }
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
  if (!followRedirects.value) options.followRedirects = false
  options.ignoreErrors = ignoreErrors.value
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
            <div v-if="urlCheckState === 'exists'" class="mt-1 flex items-center gap-1 text-xs text-amber-600">
              <AlertTriangle class="h-3 w-3" />
              该 URL 已在文档库「{{ urlCheckLibName }}」中索引
            </div>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block text-sm font-medium text-gray-700">库名 *</label>
              <input
                v-model="library"
                type="text"
                placeholder="my-docs"
                :disabled="lockLibrary"
                :class="inputCls"
                class="disabled:bg-slate-50 disabled:text-slate-400"
              />
              <div v-if="libraryCheckState === 'exists'" class="mt-1 flex items-center gap-1 text-xs text-amber-600">
                <AlertTriangle class="h-3 w-3" />
                该文档库已存在，爬取将新增版本
              </div>
              <div v-else-if="libraryCheckState === 'not_found'" class="mt-1 text-xs text-emerald-600">
                新文档库
              </div>
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-gray-700">{{ lockVersion ? '版本' : '版本 *' }}</label>
              <input
                v-model="version"
                type="text"
                :placeholder="lockVersion && !version ? '默认版本' : '完整版本号，如 1.0.0'"
                :disabled="lockVersion"
                :class="inputCls"
                class="disabled:bg-slate-50 disabled:text-slate-400"
              />
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
              <div class="flex items-center gap-6">
                <label class="flex cursor-pointer items-center gap-2">
                  <input v-model="followRedirects" type="checkbox" class="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                  <span class="text-xs text-gray-600">跟随重定向</span>
                </label>
                <label class="flex cursor-pointer items-center gap-2">
                  <input v-model="ignoreErrors" type="checkbox" class="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                  <span class="text-xs text-gray-600">忽略抓取错误</span>
                </label>
              </div>
            </div>
          </div>
        </div>
        <div class="mt-6 flex justify-end gap-3">
          <button class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50" @click="emit('close')">取消</button>
          <button
            class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!url || !library || (!lockVersion && !version.trim()) || submitting"
            @click="handleSubmit"
          >提交任务</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
