<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, ChevronRight } from 'lucide-vue-next'
import type { JsonSchema } from '@aihelms/shared'

// 递归 schema 树：admin 首个自引用 .vue，靠 defineOptions name 让模板内 <SchemaTree> 指向自身
defineOptions({ name: 'SchemaTree' })

interface Props {
  schema?: JsonSchema
  name?: string
  required?: boolean
  depth?: number
}
const props = withDefaults(defineProps<Props>(), { depth: 0, required: false })

const MAX_DEPTH = 10
const expanded = ref(props.depth === 0)

const typeText = computed(() => {
  const t = props.schema?.type
  if (!t) return ''
  return Array.isArray(t) ? t.join(' | ') : String(t)
})
const formatText = computed(() => (props.schema?.format ? String(props.schema.format) : ''))
const isRef = computed(() => Boolean(props.schema?.['$ref']))
const properties = computed(() => props.schema?.properties ?? {})
const hasProperties = computed(() => Object.keys(properties.value).length > 0)
const isArray = computed(() => typeText.value === 'array' || Boolean(props.schema?.items))
const expandable = computed(
  () => props.depth < MAX_DEPTH && (hasProperties.value || isArray.value),
)
const requiredSet = computed(() => new Set(props.schema?.required ?? []))
const isEmpty = computed(
  () =>
    !props.schema ||
    (!typeText.value &&
      !hasProperties.value &&
      !props.schema.items &&
      !props.schema.description &&
      !props.schema.enum),
)

function toggle(): void {
  expanded.value = !expanded.value
}
</script>

<template>
  <div>
    <div class="flex items-start gap-1.5 py-0.5 text-sm">
      <button
        v-if="expandable"
        class="mt-0.5 text-slate-400 hover:text-slate-600"
        type="button"
        @click="toggle"
      >
        <ChevronDown v-if="expanded" class="h-3.5 w-3.5" />
        <ChevronRight v-else class="h-3.5 w-3.5" />
      </button>
      <span v-else class="mt-0.5 inline-block w-3" />
      <span v-if="name" class="font-medium text-slate-700">{{ name }}</span>
      <span v-if="required" class="text-red-500">*</span>
      <span
        v-if="typeText"
        class="rounded bg-slate-100 px-1 py-0.5 font-mono text-xs text-slate-500"
      >{{ typeText }}{{ formatText ? ` · ${formatText}` : '' }}</span>
      <span v-if="isRef" class="truncate font-mono text-xs text-purple-500">{{ schema?.['$ref'] }}</span>
      <span v-if="schema?.description" class="truncate text-slate-400">{{ schema.description }}</span>
      <span v-if="isEmpty" class="italic text-slate-300">无结构</span>
    </div>
    <div v-if="expanded && expandable" class="ml-3 border-l border-slate-100 pl-2">
      <template v-if="hasProperties">
        <SchemaTree
          v-for="(propSchema, propName) in properties"
          :key="String(propName)"
          :schema="propSchema"
          :name="String(propName)"
          :required="requiredSet.has(String(propName))"
          :depth="depth + 1"
        />
      </template>
      <SchemaTree
        v-if="isArray && schema?.items"
        :schema="schema.items"
        name="[item]"
        :depth="depth + 1"
      />
    </div>
  </div>
</template>
