<script setup lang="ts">
import { computed } from 'vue'
import { getCurrentLocale } from '../i18n'
import zhCommon from '../i18n/locales/zh-CN/common.json'
import enCommon from '../i18n/locales/en-US/common.json'

interface Props {
  name: string
  display_name_key: string
  color?: string
  size?: 'sm' | 'md'
}

const props = withDefaults(defineProps<Props>(), {
  color: 'slate',
  size: 'md',
})

const COLOR_CLASS: Record<string, string> = {
  green: 'bg-green-50 text-green-700 ring-green-200',
  blue: 'bg-blue-50 text-blue-700 ring-blue-200',
  purple: 'bg-purple-50 text-purple-700 ring-purple-200',
  amber: 'bg-amber-50 text-amber-700 ring-amber-200',
  red: 'bg-red-50 text-red-700 ring-red-200',
  slate: 'bg-slate-100 text-slate-700 ring-slate-200',
}

const messages: Record<string, Record<string, string>> = {
  'zh-CN': zhCommon,
  'en-US': enCommon,
}

const text = computed(() => {
  const locale = getCurrentLocale()
  return (
    messages[locale]?.[props.display_name_key] ??
    messages['zh-CN'][props.display_name_key] ??
    props.name
  )
})

const colorClass = computed(() => COLOR_CLASS[props.color] ?? COLOR_CLASS.slate)
const sizeClass = computed(() =>
  props.size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs',
)
</script>

<template>
  <span
    class="inline-flex items-center rounded-md font-medium ring-1 ring-inset"
    :class="[colorClass, sizeClass]"
  >
    {{ text }}
  </span>
</template>
