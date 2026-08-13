<script setup lang="ts">
import { computed } from 'vue'
import { type Parameter } from '@aihelms/shared'

interface Props {
  parameters: Parameter[]
}
const props = defineProps<Props>()

type ParamGroup = 'path' | 'query' | 'header'
const ORDER: ParamGroup[] = ['path', 'query', 'header']

const groups = computed(() => {
  const g: Record<ParamGroup, Parameter[]> = { path: [], query: [], header: [] }
  for (const p of props.parameters) {
    if (p.in === 'path' || p.in === 'query' || p.in === 'header') g[p.in].push(p)
  }
  return g
})
const hasAny = computed(() => props.parameters.length > 0)

function paramType(p: Parameter): string {
  const ty = p.schema?.type
  if (!ty) return ''
  return Array.isArray(ty) ? ty.join(' | ') : String(ty)
}
function groupLabel(grp: ParamGroup): string {
  return grp === 'path' ? '路径参数' : grp === 'query' ? '查询参数' : '请求头'
}
</script>

<template>
  <div v-if="hasAny" class="space-y-4">
    <section v-for="grp in ORDER" :key="grp">
      <div v-if="groups[grp].length">
        <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{{ groupLabel(grp) }}</div>
        <div class="overflow-hidden rounded-md border border-slate-100">
          <table class="w-full text-sm">
            <thead class="bg-slate-50 text-slate-500">
              <tr>
                <th class="px-2 py-1.5 text-left font-medium">名称</th>
                <th class="px-2 py-1.5 text-left font-medium">类型</th>
                <th class="px-2 py-1.5 text-left font-medium">必填</th>
                <th class="px-2 py-1.5 text-left font-medium">说明</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-50">
              <tr v-for="p in groups[grp]" :key="p.name">
                <td class="px-2 py-1.5 font-mono text-slate-700">{{ p.name }}</td>
                <td class="px-2 py-1.5 font-mono text-xs text-slate-500">{{ paramType(p) || '-' }}</td>
                <td class="px-2 py-1.5">
                  <span v-if="p.required" class="text-red-500">是</span>
                  <span v-else class="text-slate-300">否</span>
                </td>
                <td class="px-2 py-1.5 text-slate-500">{{ p.description || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
  <p v-else class="py-6 text-center text-sm text-slate-300">该接口无参数</p>
</template>
