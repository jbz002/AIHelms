<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, ChevronDown, ChevronRight, Copy } from 'lucide-vue-next'
import { copyText, type ProxyResult } from '@aihelms/shared'

interface Props {
  result: ProxyResult | null
  error: string | null
}
const props = defineProps<Props>()

const showHeaders = ref(false)
const copied = ref(false)

const statusClass = computed(() => {
  const s = props.result?.status ?? 0
  if (s >= 200 && s < 300) return 'bg-green-50 text-green-700 ring-green-200'
  if (s >= 300 && s < 500) return 'bg-amber-50 text-amber-700 ring-amber-200'
  return 'bg-red-50 text-red-700 ring-red-200'
})
const isJson = computed(() => (props.result?.content_type ?? '').includes('json'))
const prettyBody = computed(() => {
  if (!props.result || !isJson.value) return props.result?.body ?? ''
  try {
    return JSON.stringify(JSON.parse(props.result.body), null, 2)
  } catch {
    return props.result.body
  }
})
const headerEntries = computed(() => Object.entries(props.result?.headers ?? {}))

async function copyBody(): Promise<void> {
  if (!props.result) return
  await copyText(props.result.body)
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 1500)
}
</script>

<template>
  <div v-if="error" class="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-600">
    {{ error }}
  </div>
  <div v-else-if="result" class="space-y-2">
    <div class="flex items-center gap-2 text-xs">
      <span
        class="inline-flex justify-center rounded px-2 py-0.5 font-mono text-xs font-semibold ring-1 ring-inset"
        :class="statusClass"
      >{{ result.status }} {{ result.status_text }}</span>
      <span class="text-slate-400">{{ result.duration_ms }} ms</span>
      <span v-if="result.truncated" class="text-amber-600">响应体已截断</span>
      <button class="ml-auto flex items-center gap-1 text-slate-400 hover:text-slate-600" @click="copyBody">
        <Check v-if="copied" class="h-3 w-3" />
        <Copy v-else class="h-3 w-3" />
        {{ copied ? '已复制' : '复制' }}
      </button>
    </div>
    <div class="rounded-md bg-slate-50">
      <button
        class="flex w-full items-center gap-1 px-2 py-1 text-xs text-slate-500 hover:text-slate-700"
        @click="showHeaders = !showHeaders"
      >
        <ChevronDown v-if="showHeaders" class="h-3 w-3" />
        <ChevronRight v-else class="h-3 w-3" />
        响应头 ({{ headerEntries.length }})
      </button>
      <div
        v-if="showHeaders"
        class="max-h-32 overflow-y-auto border-t border-slate-200 px-2 py-1 font-mono text-xs text-slate-500"
      >
        <div v-for="[k, v] in headerEntries" :key="k">{{ k }}: {{ v }}</div>
      </div>
    </div>
    <pre class="max-h-96 overflow-auto rounded-md bg-slate-900 p-3 font-mono text-sm leading-relaxed text-slate-100">{{ prettyBody || '(空响应体)' }}</pre>
  </div>
  <div v-else class="py-8 text-center text-sm text-slate-300">尚未发送请求</div>
</template>
