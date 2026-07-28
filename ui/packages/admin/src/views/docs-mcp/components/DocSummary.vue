<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { MarkdownRenderer, streamDocsMcpAsk, toast } from '@aihelms/shared'
import type { DocsMcpAskSource } from '@aihelms/shared'
import { FileText, ExternalLink, Loader2, Square, AlertCircle, X } from 'lucide-vue-next'

interface Props {
  libraryName: string
  query: string
  version?: string
}
const props = defineProps<Props>()

defineEmits<{
  close: []
}>()

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
  <div class="fixed inset-0 z-50">
    <div class="absolute inset-0 bg-black/30" @click="$emit('close')" />
    <aside
      class="absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl"
    >
      <div class="flex shrink-0 items-center justify-between border-b border-slate-200 px-5 py-3">
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold text-slate-900">AI 总结</span>
          <span v-if="phase === 'loading'" class="inline-flex items-center gap-1 text-xs text-slate-400">
            <Loader2 class="h-3 w-3 animate-spin" /> 检索与总结中...
          </span>
          <span v-else-if="phase === 'streaming'" class="text-xs text-blue-500">生成中...</span>
          <button
            v-if="phase === 'loading' || phase === 'streaming'"
            class="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
            @click="stop"
          >
            <Square class="h-3 w-3" /> 停止
          </button>
        </div>
        <button
          class="flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-100"
          aria-label="关闭"
          @click="$emit('close')"
        >
          <X class="h-4 w-4" />
        </button>
      </div>

      <div class="flex-1 overflow-y-auto px-5 py-4">
        <div
          v-if="phase === 'error'"
          class="flex items-center gap-2 rounded-md bg-red-50 p-3 text-sm text-red-600"
        >
          <AlertCircle class="h-4 w-4 shrink-0" />
          {{ errorMsg || '生成失败' }}
        </div>

        <template v-else>
          <MarkdownRenderer v-if="markdown" :content="markdown" />
          <div v-else class="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 class="h-4 w-4 animate-spin" /> 正在生成回答...
          </div>

          <div v-if="sources.length" class="mt-4 border-t border-slate-100 pt-3">
            <h4 class="mb-2 text-xs font-semibold text-slate-500">来源 ({{ sources.length }})</h4>
            <ul class="space-y-1.5">
              <li v-for="(s, i) in sources" :key="i" class="flex items-center gap-2">
                <FileText class="h-3.5 w-3.5 shrink-0 text-slate-400" />
                <a
                  :href="s.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="truncate text-sm text-blue-600 hover:text-blue-700"
                >
                  {{ s.url }}
                </a>
                <ExternalLink class="h-3 w-3 shrink-0 text-slate-300" />
                <span
                  v-if="s.score != null"
                  class="ml-auto shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500"
                >
                  {{ (s.score * 100).toFixed(1) }}%
                </span>
              </li>
            </ul>
          </div>
        </template>
      </div>
    </aside>
  </div>
</template>
