<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { type Parameter } from '@aihelms/shared'

interface Props {
  parameters: Parameter[]
}
const props = defineProps<Props>()
const { t } = useI18n()

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
  return grp === 'path' ? t('docs.op.pathParams') : grp === 'query' ? t('docs.op.queryParams') : t('docs.op.headers')
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
                <th class="px-2 py-1.5 text-left font-medium">{{ t('docs.op.col.name') }}</th>
                <th class="px-2 py-1.5 text-left font-medium">{{ t('docs.op.col.type') }}</th>
                <th class="px-2 py-1.5 text-left font-medium">{{ t('docs.op.col.required') }}</th>
                <th class="px-2 py-1.5 text-left font-medium">{{ t('docs.op.col.desc') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-50">
              <tr v-for="p in groups[grp]" :key="p.name">
                <td class="px-2 py-1.5 font-mono text-slate-700">{{ p.name }}</td>
                <td class="px-2 py-1.5 font-mono text-xs text-slate-500">{{ paramType(p) || '-' }}</td>
                <td class="px-2 py-1.5">
                  <span v-if="p.required" class="text-red-500">{{ t('docs.op.yes') }}</span>
                  <span v-else class="text-slate-300">{{ t('docs.op.no') }}</span>
                </td>
                <td class="px-2 py-1.5 text-slate-500">{{ p.description || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
  <p v-else class="py-6 text-center text-sm text-slate-300">{{ t('docs.op.noParams') }}</p>
</template>
