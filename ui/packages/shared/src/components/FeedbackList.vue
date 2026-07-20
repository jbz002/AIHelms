<script setup lang="ts">
import { computed } from 'vue'
import type { FeedbackItem, FeedbackType } from '../types/rating'

interface FeedbackLabels {
  empty?: string
  anonymous?: string
  prev?: string
  next?: string
  types?: Partial<Record<FeedbackType, string>>
}

interface Props {
  items: FeedbackItem[]
  total: number
  page: number
  pageSize: number
  labels?: FeedbackLabels
}

const props = withDefaults(defineProps<Props>(), {
  labels: () => ({}),
})

const emit = defineEmits<{
  prev: []
  next: []
}>()

const FEEDBACK_STYLE: Record<string, string> = {
  bug: 'bg-red-50 text-red-600 ring-red-200',
  suggestion: 'bg-amber-50 text-amber-600 ring-amber-200',
  praise: 'bg-emerald-50 text-emerald-600 ring-emerald-200',
}

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const hasPrev = computed(() => props.page > 1)
const hasNext = computed(() => props.page < totalPages.value)

function tagText(type: FeedbackType): string {
  if (type && props.labels?.types?.[type]) return props.labels.types[type] as string
  return ''
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <div class="space-y-3">
    <div
      v-if="items.length === 0"
      class="py-8 text-center text-sm text-slate-400"
    >
      {{ labels.empty ?? '暂无反馈' }}
    </div>

    <div
      v-for="(item, idx) in items"
      :key="idx"
      class="rounded-lg border border-slate-200 p-3"
    >
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <span class="text-amber-500 text-sm">★ {{ item.score }}</span>
          <span
            v-if="item.feedback_type"
            class="rounded px-1.5 py-0.5 text-xs ring-1 ring-inset"
            :class="FEEDBACK_STYLE[item.feedback_type] ?? 'bg-slate-50 text-slate-600 ring-slate-200'"
          >
            {{ tagText(item.feedback_type) }}
          </span>
        </div>
        <span class="text-xs text-slate-400">{{ formatDate(item.updated_at) }}</span>
      </div>
      <p v-if="item.comment" class="mt-2 whitespace-pre-wrap text-sm text-slate-700">{{ item.comment }}</p>
      <div class="mt-1 text-xs text-slate-400">{{ labels.anonymous ?? '用户' }}#{{ item.user_id }}</div>
    </div>

    <div v-if="total > pageSize" class="flex items-center justify-between pt-2">
      <button
        type="button"
        class="rounded border border-slate-200 px-3 py-1 text-sm text-slate-600 disabled:opacity-40"
        :disabled="!hasPrev"
        @click="emit('prev')"
      >
        {{ labels.prev ?? '上一页' }}
      </button>
      <span class="text-xs text-slate-500">{{ page }} / {{ totalPages }}</span>
      <button
        type="button"
        class="rounded border border-slate-200 px-3 py-1 text-sm text-slate-600 disabled:opacity-40"
        :disabled="!hasNext"
        @click="emit('next')"
      >
        {{ labels.next ?? '下一页' }}
      </button>
    </div>
  </div>
</template>
