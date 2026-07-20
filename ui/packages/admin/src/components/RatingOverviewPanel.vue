<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { StarRating, FeedbackList, getRating, listFeedbacks } from '@aihelms/shared'
import type { EntityType, FeedbackItem, FeedbackType, RatingView } from '@aihelms/shared'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

interface Props {
  entityType: EntityType
  entityId: number
}

const props = defineProps<Props>()

const view = ref<RatingView | null>(null)
const feedbacks = ref<FeedbackItem[]>([])
const feedbackTotal = ref(0)
const feedbackPage = ref(1)
const pageSize = 5
const filter = ref<FeedbackType>('')

const feedbackLabels = {
  types: { bug: '问题', suggestion: '建议', praise: '好评' } as Record<FeedbackType, string>,
}

const distOption = computed(() => {
  const dist = view.value?.distribution ?? {}
  return {
    tooltip: {},
    grid: { left: 32, right: 12, top: 16, bottom: 28 },
    xAxis: { type: 'category' as const, data: ['1星', '2星', '3星', '4星', '5星'] },
    yAxis: { type: 'value' as const, minInterval: 1 },
    series: [
      {
        type: 'bar' as const,
        data: [1, 2, 3, 4, 5].map((s) => dist[s] ?? 0),
        itemStyle: { color: '#f59e0b' },
        barMaxWidth: 36,
      },
    ],
  }
})

async function loadView() {
  try {
    view.value = await getRating(props.entityType, props.entityId)
  } catch { /* ignore */ }
}

async function loadFeedbacks(page: number) {
  feedbackPage.value = page
  try {
    const res = await listFeedbacks(
      props.entityType,
      props.entityId,
      page,
      pageSize,
      filter.value || undefined,
    )
    feedbacks.value = res.items
    feedbackTotal.value = res.total
  } catch { /* ignore */ }
}

watch(() => filter.value, () => loadFeedbacks(1))
watch(() => props.entityId, () => { loadView(); loadFeedbacks(1) })

onMounted(() => {
  loadView()
  loadFeedbacks(1)
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-4">
      <div>
        <div class="text-3xl font-bold text-slate-900">
      {{ view ? view.avg_score.toFixed(1) : '-' }}
        </div>
        <div class="text-xs text-slate-400">{{ view?.rating_count ?? 0 }} 人评分</div>
      </div>
      <StarRating :readonly-value="view?.avg_score ?? 0" readonly size="lg" />
    </div>

    <div v-if="view && view.rating_count > 0">
      <div class="mb-1 text-xs font-medium text-slate-600">评分分布</div>
      <VChart :option="distOption" style="height: 160px; width: 100%" autoresize />
    </div>

    <div>
      <div class="mb-2 flex items-center justify-between">
        <span class="text-xs font-semibold text-slate-700">用户反馈</span>
        <select
          v-model="filter"
          class="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-600 focus:outline-none"
        >
          <option value="">全部</option>
          <option value="bug">问题</option>
          <option value="suggestion">建议</option>
          <option value="praise">好评</option>
        </select>
      </div>
      <FeedbackList
        :items="feedbacks"
        :total="feedbackTotal"
        :page="feedbackPage"
        :page-size="pageSize"
        :labels="feedbackLabels"
        @prev="loadFeedbacks(feedbackPage - 1)"
        @next="loadFeedbacks(feedbackPage + 1)"
      />
    </div>
  </div>
</template>
