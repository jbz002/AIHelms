<script setup lang="ts">
import { ref, watch } from 'vue'
import { registrySearch } from '@aihelms/shared'

const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
  }>(),
  {
    placeholder: '输入关键字搜索，如 kimi / glm-5',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  select: [key: string]
}>()

const keyword = ref(props.modelValue)
const candidates = ref<string[]>([])
const open = ref(false)
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.modelValue,
  (v) => {
    keyword.value = v
  },
)

function scheduleSearch(val: string): void {
  if (timer) clearTimeout(timer)
  timer = setTimeout(async () => {
    const kw = val.trim()
    if (!kw) {
      candidates.value = []
      open.value = false
      return
    }
    loading.value = true
    try {
      candidates.value = await registrySearch(kw, 20)
      open.value = candidates.value.length > 0
    } finally {
      loading.value = false
    }
  }, 300)
}

function onInput(e: Event): void {
  const val = (e.target as HTMLInputElement).value
  keyword.value = val
  emit('update:modelValue', val)
  scheduleSearch(val)
}

function onFocus(): void {
  if (candidates.value.length) {
    open.value = true
  } else if (keyword.value.trim()) {
    scheduleSearch(keyword.value)
  }
}

function pick(key: string): void {
  keyword.value = key
  emit('update:modelValue', key)
  emit('select', key)
  open.value = false
}

function onBlur(): void {
  setTimeout(() => {
    open.value = false
  }, 150)
}
</script>

<template>
  <div class="relative w-full">
    <input
      :value="keyword"
      :placeholder="placeholder"
      class="flex h-10 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-900 placeholder:text-slate-400 focus:border-purple-500/50 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
      @input="onInput"
      @focus="onFocus"
      @blur="onBlur"
    />
    <ul
      v-if="open && (candidates.length || loading)"
      class="absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-slate-200 bg-white shadow-lg"
    >
      <li v-if="loading" class="px-3 py-2 text-xs text-slate-400">搜索中…</li>
      <li
        v-for="key in candidates"
        :key="key"
        class="cursor-pointer px-3 py-2 text-sm text-slate-700 hover:bg-purple-50"
        @mousedown.prevent="pick(key)"
      >
        {{ key }}
      </li>
    </ul>
  </div>
</template>
