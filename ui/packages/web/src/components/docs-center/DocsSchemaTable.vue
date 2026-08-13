<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { flattenSchemaRows, SCHEMA_PAD_CLASS, type JsonSchema } from '@aihelms/shared'

interface Props {
  schema?: JsonSchema
}
const props = defineProps<Props>()
const { t } = useI18n()

const rows = computed(() => flattenSchemaRows(props.schema))
const isEmpty = computed(() => rows.value.length === 0)

function padClass(depth: number): string {
  return SCHEMA_PAD_CLASS[Math.min(depth, SCHEMA_PAD_CLASS.length - 1)]
}
</script>

<template>
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
        <tr v-if="isEmpty">
          <td colspan="4" class="px-2 py-4 text-center text-slate-300">{{ t('docs.op.emptySchema') }}</td>
        </tr>
        <tr v-for="(row, i) in rows" :key="i">
          <td class="py-1.5 pr-2 font-mono text-slate-700" :class="padClass(row.depth)">{{ row.name }}</td>
          <td class="px-2 py-1.5 font-mono text-xs text-slate-500">{{ row.type || '-' }}</td>
          <td class="px-2 py-1.5">
            <span v-if="row.required" class="text-red-500">{{ t('docs.op.yes') }}</span>
            <span v-else class="text-slate-300">{{ t('docs.op.no') }}</span>
          </td>
          <td class="px-2 py-1.5 text-slate-500">{{ row.description || '-' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
