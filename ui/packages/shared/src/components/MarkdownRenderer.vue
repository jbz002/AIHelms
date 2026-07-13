<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdownToHtml } from '../utils/markdown'

interface Props {
  content: string
  /** MIME 类型。null/undefined 时默认按 markdown 渲染 */
  mimeType?: string | null
}

const props = defineProps<Props>()

const MARKDOWN_TYPES = new Set(['text/markdown', 'text/x-markdown', 'text/md'])
const isMarkdown = computed(() => !props.mimeType || MARKDOWN_TYPES.has(props.mimeType))
const html = computed(() => renderMarkdownToHtml(props.content, props.mimeType))
</script>

<template>
  <div
    v-if="isMarkdown"
    class="prose prose-sm max-w-none"
    v-html="html"
  />
  <div
    v-else
    class="overflow-auto"
    v-html="html"
  />
</template>
