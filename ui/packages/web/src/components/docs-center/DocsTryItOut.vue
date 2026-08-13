<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
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
import { Loader2, Send, Trash2, Check, ChevronDown, ChevronRight, Copy } from 'lucide-vue-next'

interface Props {
  method: HttpMethod
  path: string
  operation: Operation
  docId: number
  libraryName: string
  defaultBaseUrl?: string
}
const props = defineProps<Props>()
const { t } = useI18n()

type AuthType = 'none' | 'bearer' | 'apikey'

const libKey = encodeURIComponent(props.libraryName)
const baseUrlKey = `docs:baseurl:doc-${props.docId}`
const baseUrlsKey = `docs:baseurls:doc-${props.docId}`
const authKey = `docs:auth:${libKey}`
const tokensKey = `docs:tokens:${libKey}`

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

const baseUrl = ref(localStorage.getItem(baseUrlKey) ?? props.defaultBaseUrl?.trim() ?? '')
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
  const next = [{ label, value }, ...tokens.value.filter((item) => item.value !== value)].slice(0, 10)
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
  localStorage.removeItem(tokensKey)
  baseUrl.value = ''
  baseUrls.value = []
  authType.value = 'none'
  authValue.value = ''
  apiKeyName.value = 'X-API-Key'
  tokens.value = []
  detected.value = null
  toast.success(t('docs.tryit.memoryCleared'))
}

const pathParamsList = computed(() => (props.operation.parameters ?? []).filter((p) => p.in === 'path'))
const queryParamsList = computed(() => (props.operation.parameters ?? []).filter((p) => p.in === 'query'))
const headerParamsList = computed(() => (props.operation.parameters ?? []).filter((p) => p.in === 'header'))
const hasBody = computed(() => props.method !== 'get' && Boolean(props.operation.requestBody))

function initMap(list: Parameter[]): Record<string, string> {
  return Object.fromEntries(list.map((p) => [p.name, '']))
}
const pathParams = ref<Record<string, string>>(initMap(pathParamsList.value))
const queryParams = ref<Record<string, string>>(initMap(queryParamsList.value))
const headerParams = ref<Record<string, string>>(initMap(headerParamsList.value))
const bodyText = ref('')

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
    toast.error(t('docs.tryit.requireBaseUrl'))
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
  toast.success(t('docs.tryit.copyDone'))
}

function formatBody(): void {
  if (!bodyText.value.trim()) return
  try {
    bodyText.value = JSON.stringify(JSON.parse(bodyText.value), null, 2)
    toast.success(t('docs.tryit.formatDone'))
  } catch {
    toast.error(t('docs.tryit.formatFail'))
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
    toast.success(t('docs.tryit.detectedFilled', { key: tok.key }))
  } else {
    detectedFilled.value = false
    toast.success(t('docs.tryit.detectedCandidate', { key: tok.key }))
  }
  detected.value = tok
})

// ── 响应渲染(内联)──
const showHeaders = ref(false)
const copiedBody = ref(false)
const statusClass = computed(() => {
  const s = result.value?.status ?? 0
  if (s >= 200 && s < 300) return 'bg-green-50 text-green-700 ring-green-200'
  if (s >= 300 && s < 500) return 'bg-amber-50 text-amber-700 ring-amber-200'
  return 'bg-red-50 text-red-700 ring-red-200'
})
const isJson = computed(() => (result.value?.content_type ?? '').includes('json'))
const prettyBody = computed(() => {
  if (!result.value || !isJson.value) return result.value?.body ?? ''
  try {
    return JSON.stringify(JSON.parse(result.value.body), null, 2)
  } catch {
    return result.value.body
  }
})
const headerEntries = computed(() => Object.entries(result.value?.headers ?? {}))

async function copyBody(): Promise<void> {
  if (!result.value) return
  await copyText(result.value.body)
  copiedBody.value = true
  setTimeout(() => {
    copiedBody.value = false
  }, 1500)
}
</script>

<template>
  <div class="space-y-3">
    <!-- Base URL -->
    <div>
      <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.tryit.baseUrl') }}</label>
      <input
        v-model="baseUrl"
        list="docs-baseurls"
        :placeholder="t('docs.tryit.baseUrlPlaceholder')"
        class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:border-purple-400 focus:outline-none"
      />
      <datalist id="docs-baseurls">
        <option v-for="u in baseUrls" :key="u" :value="u" />
      </datalist>
    </div>

    <!-- 鉴权 -->
    <div class="flex flex-wrap items-end gap-2">
      <div>
        <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.tryit.auth') }}</label>
        <select v-model="authType" class="rounded-md border border-slate-200 px-2.5 py-1.5 text-sm focus:outline-none">
          <option value="none">{{ t('docs.tryit.authNone') }}</option>
          <option value="bearer">{{ t('docs.tryit.authBearer') }}</option>
          <option value="apikey">{{ t('docs.tryit.authApikey') }}</option>
        </select>
      </div>
      <input
        v-if="authType === 'apikey'"
        v-model="apiKeyName"
        :placeholder="t('docs.tryit.authHeaderName')"
        class="w-32 rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none"
      />
      <input
        v-if="authType !== 'none'"
        v-model="authValue"
        list="docs-auth-values"
        :placeholder="t('docs.tryit.authValue')"
        class="flex-1 rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none"
      />
      <datalist v-if="authType !== 'none'" id="docs-auth-values">
        <option v-for="tk in tokens" :key="tk.value" :value="tk.value">{{ tk.label }}</option>
      </datalist>
      <button
        type="button"
        class="ml-auto flex items-center gap-1 text-xs text-slate-400 hover:text-red-500"
        @click="clearMemory"
      >
        <Trash2 class="h-3.5 w-3.5" />
        {{ t('docs.tryit.clearMemory') }}
      </button>
    </div>

    <!-- 路径参数 -->
    <div v-if="pathParamsList.length">
      <div class="mb-1 text-xs font-medium text-slate-500">{{ t('docs.tryit.pathParams') }}</div>
      <div class="grid grid-cols-2 gap-2">
        <div v-for="p in pathParamsList" :key="`p-${p.name}`">
          <label class="mb-1 block text-xs text-slate-400">{{ p.name }} <span class="text-red-500">*</span></label>
          <input v-model="pathParams[p.name]" class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none" />
        </div>
      </div>
    </div>

    <!-- 查询参数 -->
    <div v-if="queryParamsList.length">
      <div class="mb-1 text-xs font-medium text-slate-500">{{ t('docs.tryit.queryParams') }}</div>
      <div class="grid grid-cols-2 gap-2">
        <div v-for="p in queryParamsList" :key="`q-${p.name}`">
          <label class="mb-1 block text-xs text-slate-400">{{ p.name }}</label>
          <input v-model="queryParams[p.name]" class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none" />
        </div>
      </div>
    </div>

    <!-- 请求头参数 -->
    <div v-if="headerParamsList.length">
      <div class="mb-1 text-xs font-medium text-slate-500">{{ t('docs.tryit.headerParams') }}</div>
      <div class="grid grid-cols-2 gap-2">
        <div v-for="p in headerParamsList" :key="`h-${p.name}`">
          <label class="mb-1 block text-xs text-slate-400">{{ p.name }}</label>
          <input v-model="headerParams[p.name]" class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-sm focus:outline-none" />
        </div>
      </div>
    </div>

    <!-- 请求体 -->
    <div v-if="hasBody">
      <div class="mb-1 flex items-center justify-between">
        <label class="block text-xs font-medium text-slate-500">{{ t('docs.tryit.body') }}</label>
        <button type="button" class="text-xs text-purple-500 hover:text-purple-600" @click="formatBody">{{ t('docs.tryit.format') }}</button>
      </div>
      <textarea
        v-model="bodyText"
        rows="4"
        :placeholder="t('docs.tryit.bodyPlaceholder')"
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
        {{ t('docs.tryit.send') }}
      </button>
    </div>

    <!-- curl 预览 -->
    <div>
      <div class="mb-1 flex items-center justify-between">
        <span class="text-xs font-medium text-slate-500">{{ t('docs.tryit.curl') }}</span>
        <button type="button" class="text-xs text-purple-500 hover:text-purple-600" @click="copyCurl">{{ t('docs.tryit.copy') }}</button>
      </div>
      <pre class="overflow-auto rounded-md bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-100">{{ curlPreview }}</pre>
    </div>

    <!-- 响应 -->
    <div>
      <div class="mb-1 text-xs font-medium text-slate-500">{{ t('docs.tryit.response') }}</div>
      <div
        v-if="detected"
        class="mb-2 flex flex-wrap items-center gap-1.5 rounded-md border border-purple-200 bg-purple-50 px-2.5 py-1.5 text-xs text-purple-700"
      >
        <span class="font-mono">{{ detected.key }}</span>：<span class="font-mono">{{ truncateVal(detected.value) }}</span>
      </div>
      <div v-if="error" class="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-600">{{ error }}</div>
      <div v-else-if="result" class="space-y-2">
        <div class="flex items-center gap-2 text-xs">
          <span
            class="inline-flex justify-center rounded px-2 py-0.5 font-mono text-xs font-semibold ring-1 ring-inset"
            :class="statusClass"
          >{{ result.status }} {{ result.status_text }}</span>
          <span class="text-slate-400">{{ t('docs.tryit.duration', { n: result.duration_ms }) }}</span>
          <span v-if="result.truncated" class="text-amber-600">{{ t('docs.tryit.bodyTruncated') }}</span>
          <button class="ml-auto flex items-center gap-1 text-slate-400 hover:text-slate-600" @click="copyBody">
            <Check v-if="copiedBody" class="h-3 w-3" />
            <Copy v-else class="h-3 w-3" />
            {{ copiedBody ? t('docs.tryit.copied') : t('docs.tryit.copy') }}
          </button>
        </div>
        <div class="rounded-md bg-slate-50">
          <button
            class="flex w-full items-center gap-1 px-2 py-1 text-xs text-slate-500 hover:text-slate-700"
            @click="showHeaders = !showHeaders"
          >
            <ChevronDown v-if="showHeaders" class="h-3 w-3" />
            <ChevronRight v-else class="h-3 w-3" />
            {{ t('docs.tryit.responseHeaders', { n: headerEntries.length }) }}
          </button>
          <div
            v-if="showHeaders"
            class="max-h-32 overflow-y-auto border-t border-slate-200 px-2 py-1 font-mono text-xs text-slate-500"
          >
            <div v-for="[k, v] in headerEntries" :key="k">{{ k }}: {{ v }}</div>
          </div>
        </div>
        <pre class="max-h-96 overflow-auto rounded-md bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-100">{{ prettyBody || t('docs.tryit.emptyBody') }}</pre>
      </div>
      <div v-else class="py-8 text-center text-sm text-slate-300">{{ t('docs.tryit.noRequest') }}</div>
    </div>
  </div>
</template>
