<script setup lang="ts">
import { computed } from 'vue'
import { flattenSchemaRows, SCHEMA_PAD_CLASS, type JsonSchema } from '@aihelms/shared'

interface Props {
  schema?: JsonSchema
}
const props = defineProps<Props>()

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
          <th class="px-2 py-1.5 text-left font-medium">名称</th>
          <th class="px-2 py-1.5 text-left font-medium">类型</th>
          <th class="px-2 py-1.5 text-left font-medium">必填</th>
          <th class="px-2 py-1.5 text-left font-medium">说明</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-50">
        <tr v-if="isEmpty">
          <td colspan="4" class="px-2 py-4 text-center text-slate-300">无结构</td>
        </tr>
        <tr v-for="(row, i) in rows" :key="i">
          <td class="py-1.5 pr-2 font-mono text-slate-700" :class="padClass(row.depth)">{{ row.name }}</td>
          <td class="px-2 py-1.5 font-mono text-xs text-slate-500">{{ row.type || '-' }}</td>
          <td class="px-2 py-1.5">
            <span v-if="row.required" class="text-red-500">是</span>
            <span v-else class="text-slate-300">否</span>
          </td>
          <td class="px-2 py-1.5 text-slate-500">{{ row.description || '-' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
