<script setup lang="ts">
import { Table2, FileText } from 'lucide-vue-next'
import { formatCost, formatNumber } from '../utils'
import type { UserDetailRow } from '../costTypes'

defineProps<{
  rows: UserDetailRow[]
}>()

const emit = defineEmits<{
  drillUser: [row: UserDetailRow]
  openUserLogs: [row: UserDetailRow]
}>()

function formatTokenCount(value: number): string {
  return Math.round(value || 0).toLocaleString()
}

function formatTokenBreakdown(row: UserDetailRow): string {
  return `${formatTokenCount(row.input_tokens)} / ${formatTokenCount(row.output_tokens)} / ${formatTokenCount(row.cache_read_tokens)} / ${formatTokenCount(row.cache_creation_tokens)}`
}

function formatSuccessRate(row: UserDetailRow): string {
  if (!row.requests) return '--'
  return `${(row.successful_requests / row.requests * 100).toFixed(1)}%`
}

function formatRealTokens(row: UserDetailRow): string {
  return formatTokenCount(
    row.fresh_input_tokens + row.output_tokens + row.cache_creation_tokens + row.cache_read_tokens,
  )
}
</script>

<template>
  <table class="min-w-[1320px] w-full text-sm">
    <thead class="sticky top-0 z-10 bg-white">
      <tr class="border-b border-slate-200 text-left text-xs text-slate-400">
        <th class="py-2.5 font-medium">姓名</th>
        <th class="py-2.5 font-medium">部门</th>
        <th class="py-2.5 text-right font-medium">LLM内部成本</th>
        <th class="py-2.5 text-right font-medium">MCP内部成本</th>
        <th class="py-2.5 text-right font-medium">内部总成本</th>
        <th class="py-2.5 text-right font-medium">外部总成本</th>
        <th class="py-2.5 text-right font-medium">差额</th>
        <th class="py-2.5 text-right font-medium">请求数</th>
        <th class="py-2.5 text-right font-medium">成功率</th>
        <th class="py-2.5 text-right font-medium">
          <div>Token</div>
          <div class="text-[10px] font-normal text-slate-300">输入/输出/缓存命中/缓存创建</div>
        </th>
        <th class="py-2.5 text-right font-medium">真实消耗Token</th>
        <th class="py-2.5 text-right font-medium">操作</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="row in rows" :key="row.user_id" class="border-b border-slate-50 last:border-0 hover:bg-slate-50/40">
        <td class="py-3 font-medium text-slate-800">{{ row.user_name }}</td>
        <td class="py-3 text-slate-700">{{ row.department || '--' }}</td>
        <td class="py-3 text-right text-slate-700">{{ formatCost(row.llm_cost) }}</td>
        <td class="py-3 text-right text-slate-700">{{ formatCost(row.mcp_cost) }}</td>
        <td class="py-3 text-right font-semibold text-slate-900">{{ formatCost(row.internal_cost) }}</td>
        <td class="py-3 text-right text-slate-700">{{ formatCost(row.external_cost) }}</td>
        <td class="py-3 text-right" :class="row.cost_diff >= 0 ? 'text-emerald-600' : 'text-red-500'">{{ formatCost(row.cost_diff) }}</td>
        <td class="py-3 text-right text-slate-700">{{ formatNumber(row.requests) }}</td>
        <td class="py-3 text-right text-slate-700">{{ formatSuccessRate(row) }}</td>
        <td class="py-3 text-right text-slate-600 whitespace-nowrap">{{ formatTokenBreakdown(row) }}</td>
        <td class="py-3 text-right text-slate-700">{{ formatRealTokens(row) }}</td>
        <td class="py-3 text-right whitespace-nowrap">
          <button type="button" class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-slate-50" @click="emit('drillUser', row)">
            <Table2 class="h-3.5 w-3.5" /> 模型明细
          </button>
          <button type="button" class="ml-1 inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-slate-50" @click="emit('openUserLogs', row)">
            <FileText class="h-3.5 w-3.5" /> 日志
          </button>
        </td>
      </tr>
      <tr v-if="!rows.length">
        <td colspan="12" class="py-8 text-center text-sm text-slate-400">暂无数据</td>
      </tr>
    </tbody>
  </table>
</template>
