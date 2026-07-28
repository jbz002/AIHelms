<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { MarkdownRenderer, streamDocsMcpAsk, toast } from '@aihelms/shared'
import type { DocsMcpAskSource } from '@aihelms/shared'
import { FileText, ExternalLink, Loader2, Square, AlertCircle } from 'lucide-vue-next'

interface Props {
  libraryName: string
  query: string
  version?: string
}
const props = defineProps<Props>()

type Phase = 'loading' | 'streaming' | 'done' | 'error'
const phase = ref<Phase>('loading')
const sources = ref<DocsMcpAskSource[]>([])
const markdown = ref('')
const errorMsg = ref('')
let controller: AbortController | null = null

function run(): void {
  controller?.abort()
  controller = new AbortController()
  phase.value = 'loading'
  sources.value = []
  markdown.value = ''
  errorMsg.value = ''

  streamDocsMcpAsk(
    props.libraryName,
    { query: props.query, version: props.version },
    {
      onSources: (s) => {
        sources.value = s
        if (phase.value !== 'error') phase.value = 'streaming'
      },
      onDelta: (c) => {
        if (!c) return
        markdown.value += c
        if (phase.value !== 'error') phase.value = 'streaming'
      },
      onDone: () => {
        phase.value = 'done'
      },
      onError: (m) => {
        errorMsg.value = m
        phase.value = 'error'
      },
    },
    controller.signal,
  ).catch((e: unknown) => {
    if ((e as Error)?.name !== 'AbortError') {
      toast.error((e as Error).message || 'AI 总结失败')
    }
  })
}

function stop(): void {
  controller?.abort()
  if (phase.value === 'loading' || phase.value === 'streaming') phase.value = 'done'
}

onMounted(run)
onUnmounted(() => controller?.abort())
</script>

<template>
  <div class="mt-4 rounded-lg border border-gray-200 bg-white p-4">
    <div class="mb-3 flex items-center gap-2">
      <span class="text-sm font-semibold text-gray-700">AI 总结</span>
      <span v-if="phase === 'loading'" class="inline-flex items-center gap-1 text-xs text-gray-400">
        <Loader2 class="h-3 w-3 animate-spin" /> 检索与总结中...
      </span>
      <span v-else-if="phase === 'streaming'" class="text-xs text-blue-500">生成中...</span>
      <button
        v-if="phase === 'loading' || phase === 'streaming'"
        class="ml-auto inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
        @click="stop"
      >
        <Square class="h-3 w-3" /> 停止
      </button>
    </div>

    <div
      v-if="phase === 'error'"
      class="flex items-center gap-2 rounded-md bg-red-50 p-3 text-sm text-red-600"
    >
      <AlertCircle class="h-4 w-4 shrink-0" />
      {{ errorMsg || '生成失败' }}
    </div>

    <template v-else>
      <div
        v-if="markdown || phase === 'streaming' || phase === 'done'"
        class="border-b border-gray-100 pb-3"
      >
        <MarkdownRenderer v-if="markdown" :content="markdown" />
        <div v-else class="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 class="h-4 w-4 animate-spin" /> 正在生成回答...
        </div>
      </div>

      <div v-if="sources.length" class="mt-3">
        <h4 class="mb-2 text-xs font-semibold text-gray-500">来源 ({{ sources.length }})</h4>
        <ul class="space-y-1.5">
          <li v-for="(s, i) in sources" :key="i" class="flex items-center gap-2">
            <FileText class="h-3.5 w-3.5 shrink-0 text-gray-400" />
            <a
              :href="s.url"
              target="_blank"
              rel="noopener noreferrer"
              class="truncate text-sm text-blue-600 hover:text-blue-700"
            >
              {{ s.url }}
            </a>
            <ExternalLink class="h-3 w-3 shrink-0 text-gray-300" />
            <span
              v-if="s.score != null"
              class="ml-auto shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500"
            >
              {{ (s.score * 100).toFixed(1) }}%
            </span>
          </li>
        </ul>
      </div>
    </template>
  </div>
</template>
