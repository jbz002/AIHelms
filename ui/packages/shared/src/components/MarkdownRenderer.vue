<script setup lang="ts">
import { computed, ref, watch, onMounted, nextTick } from 'vue'
import { renderMarkdownToHtml, renderMermaidBlocks } from '../utils/markdown'

interface Props {
  content: string
  /** MIME 类型。null/undefined 时默认按 markdown 渲染 */
  mimeType?: string | null
}

const props = defineProps<Props>()

const MARKDOWN_TYPES = new Set(['text/markdown', 'text/x-markdown', 'text/md', 'text/plain'])
const isMarkdown = computed(() => !props.mimeType || MARKDOWN_TYPES.has(props.mimeType))
const html = computed(() => renderMarkdownToHtml(props.content, props.mimeType))

const containerRef = ref<HTMLElement | null>(null)

async function processMermaid(): Promise<void> {
  await nextTick()
  if (containerRef.value) {
    await renderMermaidBlocks(containerRef.value)
  }
}

onMounted(processMermaid)
watch(() => props.content, processMermaid)
</script>

<template>
  <div
    v-if="isMarkdown"
    ref="containerRef"
    class="prose prose-sm max-w-none"
    v-html="html"
  />
  <div
    v-else
    ref="containerRef"
    class="overflow-auto"
    v-html="html"
  />
</template>
