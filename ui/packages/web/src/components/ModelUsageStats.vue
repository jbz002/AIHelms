<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getEfficiencyModelStats } from '@aihelms/shared'
import type { EfficiencyKpi, UserModelStat } from '@aihelms/shared/src/types/efficiency'

const props = defineProps<{
  start: string
  end: string
  overview: EfficiencyKpi | null
  modelIcons: Record<string, string>
}>()

const { t } = useI18n()
const rows = ref<UserModelStat[]>([])
const isLoading = ref(false)

async function loadStats(): Promise<void> {
  isLoading.value = true
  try {
    const data = await getEfficiencyModelStats({
      scope: 'self',
      start_date: props.start,
      end_date: props.end,
    }).catch(() => null)
    rows.value = data?.items ?? []
  } finally {
    isLoading.value = false
  }
}

watch(() => props.start, () => { loadStats() }, { immediate: true })

function formatTokens(v: number | null | undefined): string {
  const n = Number(v ?? 0) || 0
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatCount(v: number | null | undefined): string {
  return (Number(v ?? 0) || 0).toLocaleString()
}

function formatPercent(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return `${v >= 99.95 ? v.toFixed(0) : v.toFixed(1)}%`
}

function formatMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  if (v >= 1000) return `${(v / 1000).toFixed(1)}s`
  return `${Math.round(v)}ms`
}

function tokensTitle(row: UserModelStat): string {
  return t('identity.usageStats.tokensTooltip', {
    fresh: formatCount(row.fresh_input_tokens),
    output: formatCount(row.output_tokens),
    creation: formatCount(row.cache_creation_tokens),
    read: formatCount(row.cache_read_tokens),
  })
}

function costTitle(row: UserModelStat): string {
  return t('identity.usageStats.avgCostTooltip', {
    value: row.avg_cost_per_request !== null ? `¥${row.avg_cost_per_request.toFixed(4)}` : '--',
  })
}

function iconUrl(row: UserModelStat): string {
  return props.modelIcons[row.platform_model_id] || '/icons/v1/default.svg'
}

const hasData = computed(() => rows.value.length > 0)
</script>

<template>
  <div class="mt-5" :class="{ 'opacity-50 pointer-events-none': isLoading }">
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div class="rounded-xl bg-slate-50/80 px-4 py-3">
        <div class="text-xs text-slate-400">{{ t('identity.usageStats.realTokens') }}</div>
        <div class="mt-1 text-base font-semibold text-slate-900" :title="t('identity.usageStats.realTokensHint')">
          {{ formatTokens(overview?.real_total_tokens) }}
        </div>
      </div>
      <div class="rounded-xl bg-slate-50/80 px-4 py-3">
        <div class="text-xs text-slate-400">{{ t('identity.usageStats.cacheHitRate') }}</div>
        <div class="mt-1 text-base font-semibold text-slate-900" :title="t('identity.usageStats.cacheHitRateHint')">
          {{ formatPercent(overview?.cache_hit_rate) }}
        </div>
      </div>
      <div class="rounded-xl bg-slate-50/80 px-4 py-3">
        <div class="text-xs text-slate-400">{{ t('identity.usageStats.successRate') }}</div>
        <div class="mt-1 text-base font-semibold text-slate-900">{{ formatPercent(overview?.success_rate) }}</div>
      </div>
      <div class="rounded-xl bg-slate-50/80 px-4 py-3">
        <div class="text-xs text-slate-400">{{ t('identity.usageStats.avgLatency') }}</div>
        <div class="mt-1 text-base font-semibold text-slate-900">{{ formatMs(overview?.avg_latency_ms) }}</div>
      </div>
    </div>
    <div class="mt-4 overflow-x-auto">
      <table class="w-full min-w-[560px] text-left text-sm">
        <thead>
          <tr class="border-b border-slate-100 text-xs text-slate-400">
            <th class="py-2 pr-3 font-medium">{{ t('identity.usageStats.model') }}</th>
            <th class="px-3 py-2 font-medium">{{ t('identity.usageStats.requests') }}</th>
            <th class="px-3 py-2 font-medium">{{ t('identity.usageStats.tokens') }}</th>
            <th class="px-3 py-2 font-medium">{{ t('identity.usageStats.cost') }}</th>
            <th class="px-3 py-2 font-medium">{{ t('identity.usageStats.successRate') }}</th>
            <th class="px-3 py-2 font-medium">{{ t('identity.usageStats.speed') }}</th>
            <th class="py-2 pl-3 font-medium">{{ t('identity.usageStats.firstToken') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!hasData">
            <td colspan="7" class="py-6 text-center text-xs text-slate-400">{{ t('identity.usageStats.empty') }}</td>
          </tr>
          <tr v-for="row in rows" :key="row.model" class="border-b border-slate-50 last:border-0">
            <td class="py-2.5 pr-3">
              <div class="flex items-center gap-2">
                <img :src="iconUrl(row)" alt="" class="h-5 w-5 shrink-0 rounded" />
                <div class="min-w-0">
                  <div class="truncate font-medium text-slate-900" :title="row.model">{{ row.platform_model_name }}</div>
                  <div class="truncate text-xs text-slate-400">{{ row.platform_model_id }}</div>
                </div>
              </div>
            </td>
            <td class="px-3 py-2.5 tabular-nums text-slate-700">{{ formatCount(row.request_count) }}</td>
            <td class="px-3 py-2.5 tabular-nums text-slate-700" :title="tokensTitle(row)">{{ formatTokens(row.real_total_tokens) }}</td>
            <td class="px-3 py-2.5 tabular-nums font-medium text-slate-900" :title="costTitle(row)">¥{{ row.internal_cost.toFixed(2) }}</td>
            <td class="px-3 py-2.5 tabular-nums text-slate-700">{{ formatPercent(row.success_rate) }}</td>
            <td class="px-3 py-2.5 tabular-nums text-slate-700">
              {{ row.speed_tokens_per_sec !== null ? `${row.speed_tokens_per_sec} tok/s` : '--' }}
            </td>
            <td class="py-2.5 pl-3 tabular-nums text-slate-700">{{ formatMs(row.first_token_ms) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
