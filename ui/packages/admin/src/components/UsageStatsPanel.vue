<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { getMcpUsageStats, getSkillUsageStats } from '@aihelms/shared'
import type { EntityType, McpUsageStats, SkillUsageStats, StatsRange } from '@aihelms/shared'

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent])

interface Props {
  entityType: EntityType
  entityId: number
}

const props = defineProps<Props>()

const isMcp = computed(() => props.entityType === 'mcp_server')
const days = ref<StatsRange>(30)
const loading = ref(false)
const mcpStats = ref<McpUsageStats | null>(null)
const skillStats = ref<SkillUsageStats | null>(null)

const RANGE_OPTIONS: StatsRange[] = [7, 30, 90]

interface Kpi { label: string; value: string }
const kpis = computed<Kpi[]>(() => {
  if (isMcp.value) {
    const s = mcpStats.value
    return [
      { label: '总调用', value: String(s?.total_calls ?? 0) },
      { label: '独立用户', value: String(s?.unique_users ?? 0) },
      { label: '总成本', value: `${(s?.total_cost ?? 0).toFixed(2)} 元` },
      { label: '平均耗时', value: `${s?.avg_duration_ms ?? 0} ms` },
    ]
  }
  const s = skillStats.value
  return [
    { label: '总下载', value: String(s?.total_downloads ?? 0) },
    { label: '独立用户', value: String(s?.unique_users ?? 0) },
    { label: '手动下载', value: String(s?.manual_downloads ?? 0) },
    { label: 'Agent 下载', value: String(s?.agent_downloads ?? 0) },
  ]
})

const trendOption = computed(() => {
  const stats = isMcp.value ? mcpStats.value : skillStats.value
  const trend = stats?.trend ?? []
  return {
    tooltip: { trigger: 'axis' as const },
    grid: { left: 36, right: 12, top: 16, bottom: 28 },
    xAxis: { type: 'category' as const, data: trend.map((p) => p.date.slice(5)) },
    yAxis: { type: 'value' as const, minInterval: 1 },
    series: [
      {
        type: 'line' as const,
        smooth: true,
        data: trend.map((p) => p.count),
        areaStyle: { opacity: 0.15 },
        itemStyle: { color: '#6366f1' },
      },
    ],
  }
})

const distOption = computed(() => {
  if (isMcp.value) {
    const items = mcpStats.value?.tool_distribution ?? []
    return {
      tooltip: {},
      grid: { left: 36, right: 12, top: 16, bottom: 40 },
      xAxis: { type: 'category' as const, data: items.map((i) => i.tool_name), axisLabel: { rotate: 30 } },
      yAxis: { type: 'value' as const, minInterval: 1 },
      series: [{ type: 'bar' as const, data: items.map((i) => i.count), itemStyle: { color: '#06b6d4' }, barMaxWidth: 32 }],
    }
  }
  const items = skillStats.value?.action_distribution ?? []
  return {
    tooltip: {},
    grid: { left: 36, right: 12, top: 16, bottom: 28 },
    xAxis: { type: 'category' as const, data: items.map((i) => i.action) },
    yAxis: { type: 'value' as const, minInterval: 1 },
    series: [{ type: 'bar' as const, data: items.map((i) => i.count), itemStyle: { color: '#10b981' }, barMaxWidth: 48 }],
  }
})

async function load() {
  loading.value = true
  try {
    if (isMcp.value) mcpStats.value = await getMcpUsageStats(props.entityId, days.value)
    else skillStats.value = await getSkillUsageStats(props.entityId, days.value)
  } catch { /* ignore */ }
  finally { loading.value = false }
}

watch(() => days.value, load)
watch(() => props.entityId, load)

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-1 rounded-lg bg-slate-100 p-1 w-fit">
      <button
        v-for="r in RANGE_OPTIONS"
        :key="r"
        class="rounded-md px-3 py-1 text-xs font-medium transition-all"
        :class="days === r ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
        @click="days = r"
      >
        近 {{ r }} 天
      </button>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-10">
      <div class="h-6 w-6 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
    </div>

    <template v-else>
      <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div v-for="kpi in kpis" :key="kpi.label" class="rounded-lg border border-slate-200 bg-white p-3">
          <div class="text-xs text-slate-400">{{ kpi.label }}</div>
          <div class="mt-1 text-lg font-semibold text-slate-900">{{ kpi.value }}</div>
        </div>
      </div>

      <div>
        <div class="mb-1 text-xs font-medium text-slate-600">调用趋势</div>
        <VChart :option="trendOption" style="height: 220px; width: 100%" autoresize />
      </div>

      <div>
        <div class="mb-1 text-xs font-medium text-slate-600">
          {{ isMcp ? '工具调用分布' : '下载方式分布' }}
        </div>
        <VChart :option="distOption" style="height: 240px; width: 100%" autoresize />
      </div>
    </template>
  </div>
</template>
