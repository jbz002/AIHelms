<script setup lang="ts">
import { computed, ref } from 'vue'
import type { HttpMethod } from '@aihelms/shared'
import { ChevronDown, ChevronRight, Search } from 'lucide-vue-next'

interface EndpointItem {
  key: string
  method: HttpMethod
  path: string
  summary?: string
  category: string
}

interface Props {
  endpoints: EndpointItem[]
  selectedKey: string | null
}
const props = defineProps<Props>()
const emit = defineEmits<{ select: [key: string] }>()

const keyword = ref('')
// 折叠状态：每个分类分组独立可折叠（仿 EndpointList collapsedTags idiom）
const collapsedTags = ref<Set<string>>(new Set())

const METHOD_COLOR: Record<HttpMethod, string> = {
  get: 'bg-green-50 text-green-700 ring-green-200',
  post: 'bg-blue-50 text-blue-700 ring-blue-200',
  put: 'bg-amber-50 text-amber-700 ring-amber-200',
  delete: 'bg-red-50 text-red-700 ring-red-200',
  patch: 'bg-purple-50 text-purple-700 ring-purple-200',
}

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return props.endpoints
  return props.endpoints.filter(
    (e) =>
      e.path.toLowerCase().includes(kw) ||
      (e.summary ?? '').toLowerCase().includes(kw) ||
      e.method.includes(kw) ||
      e.category.toLowerCase().includes(kw),
  )
})

const groups = computed(() => {
  const map = new Map<string, EndpointItem[]>()
  for (const e of filtered.value) {
    const tag = e.category || '默认'
    if (!map.has(tag)) map.set(tag, [])
    map.get(tag)!.push(e)
  }
  return Array.from(map, ([tag, items]) => ({ tag, items }))
})

function toggleTag(tag: string): void {
  const next = new Set(collapsedTags.value)
  if (next.has(tag)) next.delete(tag)
  else next.add(tag)
  collapsedTags.value = next
}
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="border-b border-slate-100 p-3">
      <div class="relative">
        <Search class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          v-model="keyword"
          placeholder="搜索接口..."
          class="w-full rounded-md border border-slate-200 py-1.5 pl-8 pr-2 text-sm focus:border-purple-400 focus:outline-none"
        />
      </div>
    </div>
    <div class="flex-1 overflow-y-auto p-2">
      <div v-for="g in groups" :key="g.tag" class="mb-2">
        <button
          type="button"
          class="flex w-full items-center gap-1 rounded px-1 py-1 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-700"
          @click="toggleTag(g.tag)"
        >
          <ChevronDown v-if="!collapsedTags.has(g.tag)" class="h-3.5 w-3.5 shrink-0" />
          <ChevronRight v-else class="h-3.5 w-3.5 shrink-0" />
          <span class="truncate">{{ g.tag }}</span>
          <span class="ml-auto font-normal text-slate-400">{{ g.items.length }}</span>
        </button>
        <div v-show="!collapsedTags.has(g.tag)">
          <button
            v-for="item in g.items"
            :key="item.key"
            type="button"
            class="mb-0.5 flex w-full items-center gap-2 rounded-md px-2 py-2 text-left"
            :class="selectedKey === item.key ? 'bg-purple-50' : 'hover:bg-slate-50'"
            @click="emit('select', item.key)"
          >
            <span
              class="inline-flex w-14 shrink-0 justify-center rounded px-1.5 py-0.5 font-mono text-xs font-semibold ring-1 ring-inset"
              :class="METHOD_COLOR[item.method]"
            >{{ item.method.toUpperCase() }}</span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-medium text-slate-700">{{ item.summary || item.path }}</span>
              <span v-if="item.summary" class="block truncate font-mono text-xs text-slate-400">{{ item.path }}</span>
            </span>
          </button>
        </div>
      </div>
      <div v-if="!groups.length" class="py-8 text-center text-sm text-slate-300">无匹配接口</div>
    </div>
  </div>
</template>
