<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  buildCurl,
  proxyDocumentRequest,
  copyText,
  toast,
  type HttpMethod,
  type Operation,
  type Parameter,
  type ProxyResult,
} from '@aihelms/shared'
import { Loader2, Send, Trash2 } from 'lucide-vue-next'
import ResponseViewer from './ResponseViewer.vue'

interface Props {
  method: HttpMethod
  path: string
  operation: Operation
  docId: number
  libraryName: string
}
const props = defineProps<Props>()

type AuthType = 'none' | 'bearer' | 'apikey'

const libKey = encodeURIComponent(props.libraryName)
const baseUrlKey = `debugger:baseurl:${libKey}`
const baseUrlsKey = `debugger:baseurls:${libKey}`
const authKey = `debugger:auth:${libKey}`

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

const baseUrl = ref(localStorage.getItem(baseUrlKey) ?? '')
const baseUrls = ref<string[]>(readJson<string[]>(baseUrlsKey, []))
watch(baseUrl, (v) => {
  localStorage.setItem(baseUrlKey, v)
  const trimmed = v.trim()
  if (!trimmed) return
  const next = [trimmed, ...baseUrls.value.filter((u) => u !== trimmed)].slice(0, 10)
  baseUrls.value = next
  localStorage.setItem(baseUrlsKey, JSON.stringify(next))
})

interface SavedAuth {
  authType: AuthType
  authValue: string
  apiKeyName: string
}
const savedAuth = readJson<SavedAuth | null>(authKey, null)
const authType = ref<AuthType>(savedAuth?.authType ?? 'none')
const authValue = ref(savedAuth?.authValue ?? '')
const apiKeyName = ref(savedAuth?.apiKeyName ?? 'X-API-Key')
watch([authType, authValue, apiKeyName], () => {
  localStorage.setItem(
    authKey,
    JSON.stringify({
      authType: authType.value,
      authValue: authValue.value,
      apiKeyName: apiKeyName.value,
    } satisfies SavedAuth),
  )
})

const tokensKey = `debugger:tokens:${libKey}`
interface TokenCandidate {
  label: string
  value: string
}
const tokens = ref<TokenCandidate[]>(readJson<TokenCandidate[]>(tokensKey, []))

interface DetectedToken {
  key: string
  value: string
}
const detected = ref<DetectedToken | null>(null)
const detectedFilled = ref(false)

const TOKEN_KEYS = [
  'access_token', 'id_token', 'token',
  'api_key', 'apikey', 'api-key', 'api_token',
  'secret', 'secret_key',
  'authorization', 'auth', 'bearer', 'jwt',
  'session', 'session_id',
]

function stripAuthPrefix(v: string): string {
  const m = v.match(/^\s*(?:bearer|token)\s+(.+)$/i)
  return m ? m[1].trim() : v.trim()
}

function collectTokens(node: unknown, out: DetectedToken[]): void {
  if (Array.isArray(node)) {
    for (const item of node) collectTokens(item, out)
    return
  }
  if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      if (typeof v === 'string' && TOKEN_KEYS.includes(k.toLowerCase())) {
        const val = stripAuthPrefix(v)
        if (val && val.length <= 2048) out.push({ key: k, value: val })
      } else {
        collectTokens(v, out)
      }
    }
  }
}

function extractTokenFromResult(r: ProxyResult): DetectedToken | null {
  if (!r.content_type.includes('json')) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(r.body)
  } catch {
    return null
  }
  const found: DetectedToken[] = []
  collectTokens(parsed, found)
  if (!found.length) return null
  found.sort(
    (a, b) =>
      TOKEN_KEYS.indexOf(a.key.toLowerCase()) - TOKEN_KEYS.indexOf(b.key.toLowerCase()),
  )
  return found[0]
}

function pushToken(label: string, value: string): void {
  const next = [{ label, value }, ...tokens.value.filter((t) => t.value !== value)].slice(0, 10)
  tokens.value = next
  localStorage.setItem(tokensKey, JSON.stringify(next))
}

function truncateVal(v: string): string {
  return v.length > 24 ? `${v.slice(0, 24)}…` : v
}

function clearMemory(): void {
  localStorage.removeItem(baseUrlKey)
  localStorage.removeItem(baseUrlsKey)
  localStorage.removeItem(authKey)
  baseUrl.value = ''
  baseUrls.value = []
  authType.value = 'none'
  authValue.value = ''
  apiKeyName.value = 'X-API-Key'
  tokens.value = []
  detected.value = null
  toast.success('已清除该库的记忆')
}

const pathParamsList = computed(() => (props.operation.parameters ?? []).filter((p) => p.in === 'path'))
const queryParamsList = computed(() => (props.operation.parameters ?? []).filter((p) => p.in === 'query'))
const headerParamsList = computed(() => (props.operation.parameters ?? []).filter((p) => p.in === 'header'))
const hasBody = computed(() => props.method !== 'get' && Boolean(props.operation.requestBody))

const pathParams = ref<Record<string, string>>(initMap(pathParamsList.value))
const queryParams = ref<Record<string, string>>(initMap(queryParamsList.value))
const headerParams = ref<Record<string, string>>(initMap(headerParamsList.value))
const bodyText = ref('')

function initMap(list: Parameter[]): Record<string, string> {
  return Object.fromEntries(list.map((p) => [p.name, '']))
}

const effectiveHeaders = computed<Record<string, string>>(() => {
  const h: Record<string, string> = {}
  for (const [k, v] of Object.entries(headerParams.value)) if (v) h[k] = v
  if (authType.value === 'bearer' && authValue.value) h['Authorization'] = `Bearer ${authValue.value}`
  if (authType.value === 'apikey' && authValue.value && apiKeyName.value) h[apiKeyName.value] = authValue.value
  if (hasBody.value && bodyText.value && !h['Content-Type']) h['Content-Type'] = 'application/json'
  return h
})

const filledPath = computed(() => {
  let p = props.path
  for (const { name } of pathParamsList.value) {
    p = p.replace(`{${name}}`, encodeURIComponent(pathParams.value[name] ?? ''))
  }
  return p
})
const queryRecord = computed(() => {
  const q: Record<string, string> = {}
  for (const { name } of queryParamsList.value) {
    const v = queryParams.value[name]
    if (v) q[name] = v
  }
  return q
})
const fullUrl = computed(() => {
  const base = baseUrl.value.trim().replace(/\/+$/, '')
  return `${base}${filledPath.value}`
})
const urlWithQuery = computed(() => {
  const qs = new URLSearchParams(queryRecord.value).toString()
  return qs ? `${fullUrl.value}?${qs}` : fullUrl.value
})

const curlPreview = computed(() =>
  buildCurl({
    method: props.method,
    url: fullUrl.value,
    queryParams: queryRecord.value,
    headers: effectiveHeaders.value,
    body: hasBody.value ? bodyText.value || null : null,
  }),
)

const sending = ref(false)
const result = ref<ProxyResult | null>(null)
const error = ref<string | null>(null)

async function send(): Promise<void> {
  if (!baseUrl.value.trim()) {
    toast.error('请填写 Base URL')
    return
  }
  sending.value = true
  error.value = null
  result.value = null
  try {
    result.value = await proxyDocumentRequest(props.docId, {
      method: props.method,
      url: urlWithQuery.value,
      headers: effectiveHeaders.value,
      body: hasBody.value ? bodyText.value || null : null,
    })
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    sending.value = false
  }
}

async function copyCurl(): Promise<void> {
  await copyText(curlPreview.value)
  toast.success('curl 已复制')
}

function formatBody(): void {
  if (!bodyText.value.trim()) return
  try {
    bodyText.value = JSON.stringify(JSON.parse(bodyText.value), null, 2)
    toast.success('已格式化')
  } catch {
    toast.error('JSON 格式有误')
  }
}

watch(result, (r) => {
  detected.value = null
  if (!r) return
  const tok = extractTokenFromResult(r)
  if (!tok) return
  pushToken(tok.key, tok.value)
  if (!authValue.value.trim()) {
    if (authType.value === 'none') authType.value = 'bearer'
    authValue.value = tok.value
    detectedFilled.value = true
    toast.success(`检测到 ${tok.key}，已填入鉴权`)
  } else {
    detectedFilled.value = false
    toast.success(`检测到 ${tok.key}，已加入候选`)
  }
  detected.value = tok
})
</script>

<template>
  <div class="space-y-3">
    <!-- Base URL -->
    <div>
      <label class="mb-1 block text-xs font-medium text-slate-500">Base URL</label>
      <input
        v-model="baseUrl"
        list="debugger-baseurls"
        placeholder="https://api.example.com"
        class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:border-purple-400 focus:outline-none appearance-none [&::-webkit-calendar-picker-indicator]:!hidden"
      />
      <datalist id="debugger-baseurls">
        <option v-for="u in baseUrls" :key="u" :value="u" />
      </datalist>
    </div>

    <!-- 鉴权 -->
    <div class="flex flex-wrap items-end gap-2">
      <div>
        <label class="mb-1 block text-xs font-medium text-slate-500">鉴权</label>
        <select v-model="authType" class="rounded-md border border-slate-200 px-2.5 py-1.5 text-sm focus:outline-none">
          <option value="none">无</option>
          <option value="bearer">Bearer Token</option>
          <option value="apikey">API Key (Header)</option>
        </select>
      </div>
      <input
        v-if="authType === 'apikey'"
        v-model="apiKeyName"
        placeholder="Header 名"
        class="w-32 rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none"
      />
      <input
        v-if="authType !== 'none'"
        v-model="authValue"
        list="debugger-auth-values"
        :type="authType === 'bearer' ? 'text' : 'text'"
        placeholder="凭据值"
        class="flex-1 rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none"
      />
      <datalist v-if="authType !== 'none'" id="debugger-auth-values">
        <option v-for="t in tokens" :key="t.value" :value="t.value">{{ t.label }}</option>
      </datalist>
      <button
        type="button"
        class="ml-auto flex items-center gap-1 text-xs text-slate-400 hover:text-red-500"
        @click="clearMemory"
      >
        <Trash2 class="h-3.5 w-3.5" />
        清除记忆
      </button>
    </div>

    <!-- 路径参数 -->
    <div v-if="pathParamsList.length" class="grid grid-cols-2 gap-2">
      <div v-for="p in pathParamsList" :key="`p-${p.name}`">
        <label class="mb-1 block text-xs font-medium text-slate-500">{{ p.name }} <span class="text-red-500">*</span></label>
        <input v-model="pathParams[p.name]" class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none" />
      </div>
    </div>

    <!-- 查询参数 -->
    <div v-if="queryParamsList.length" class="grid grid-cols-2 gap-2">
      <div v-for="p in queryParamsList" :key="`q-${p.name}`">
        <label class="mb-1 block text-xs font-medium text-slate-500">{{ p.name }}</label>
        <input v-model="queryParams[p.name]" class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none" />
      </div>
    </div>

    <!-- 请求头参数 -->
    <div v-if="headerParamsList.length" class="grid grid-cols-2 gap-2">
      <div v-for="p in headerParamsList" :key="`h-${p.name}`">
        <label class="mb-1 block text-xs font-medium text-slate-500">{{ p.name }}</label>
        <input v-model="headerParams[p.name]" class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none" />
      </div>
    </div>

    <!-- 请求体 -->
    <div v-if="hasBody">
      <div class="mb-1 flex items-center justify-between">
        <label class="block text-xs font-medium text-slate-500">请求体 (JSON)</label>
        <button type="button" class="text-xs text-purple-500 hover:text-purple-600" @click="formatBody">格式化</button>
      </div>
      <textarea
        v-model="bodyText"
        rows="4"
        placeholder='{ "key": "value" }'
        class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none"
      />
    </div>

    <!-- 发送 -->
    <div class="flex items-center gap-2">
      <button
        type="button"
        class="flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        :disabled="sending"
        @click="send"
      >
        <Loader2 v-if="sending" class="h-4 w-4 animate-spin" />
        <Send v-else class="h-4 w-4" />
        发送请求
      </button>
    </div>

    <!-- curl 预览 -->
    <div>
      <div class="mb-1 flex items-center justify-between">
        <span class="text-xs font-medium text-slate-500">curl</span>
        <button type="button" class="text-xs text-purple-500 hover:text-purple-600" @click="copyCurl">复制</button>
      </div>
      <pre class="overflow-auto rounded-md bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-100">{{ curlPreview }}</pre>
    </div>

    <!-- 响应 -->
    <div>
      <div class="mb-1 text-xs font-medium text-slate-500">响应</div>
      <div
        v-if="detected"
        class="mb-2 flex flex-wrap items-center gap-1.5 rounded-md border border-purple-200 bg-purple-50 px-2.5 py-1.5 text-xs text-purple-700"
      >
        <span>检测到 <span class="font-mono font-medium">{{ detected.key }}</span>：<span class="font-mono">{{ truncateVal(detected.value) }}</span></span>
        <span class="text-purple-400">→ {{ detectedFilled ? '已填入鉴权' : '已加入候选' }}</span>
      </div>
      <ResponseViewer :result="result" :error="error" />
    </div>
  </div>
</template>
