<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { HttpMethod, Operation, OpenApiSpec } from '@aihelms/shared'
import EndpointList from './EndpointList.vue'
import OperationDetail from './OperationDetail.vue'

interface Props {
  spec: OpenApiSpec
  docId: number
  libraryName: string
}
const props = defineProps<Props>()

interface EndpointItem {
  key: string
  method: HttpMethod
  path: string
  summary?: string
  tags: string[]
}

const METHODS: HttpMethod[] = ['get', 'post', 'put', 'delete', 'patch']

const endpoints = computed<EndpointItem[]>(() => {
  const list: EndpointItem[] = []
  for (const [path, pathItem] of Object.entries(props.spec.paths)) {
    for (const m of METHODS) {
      const op = pathItem?.[m]
      if (op) {
        list.push({ key: `${m} ${path}`, method: m, path, summary: op.summary, tags: op.tags ?? [] })
      }
    }
  }
  return list
})

const selectedKey = ref<string | null>(null)
const selected = computed(() => endpoints.value.find((e) => e.key === selectedKey.value) ?? null)
const selectedOperation = computed<Operation | null>(() => {
  if (!selected.value) return null
  return props.spec.paths[selected.value.path]?.[selected.value.method] ?? null
})

watch(
  endpoints,
  (list) => {
    if (list.length && !selectedKey.value) selectedKey.value = list[0].key
  },
  { immediate: true },
)
</script>

<template>
  <div class="flex h-[calc(100vh-8rem)] gap-4 overflow-hidden">
    <!-- 左：接口列表 -->
    <div class="flex w-80 shrink-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <EndpointList :endpoints="endpoints" :selected-key="selectedKey" @select="selectedKey = $event" />
    </div>

    <!-- 右：操作详情 -->
    <div class="flex flex-1 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <OperationDetail
        v-if="selected && selectedOperation"
        :method="selected.method"
        :path="selected.path"
        :operation="selectedOperation"
        :doc-id="docId"
        :library-name="libraryName"
      />
      <div v-else class="flex h-full items-center justify-center text-sm text-slate-400">
        请从左侧选择接口
      </div>
    </div>
  </div>
</template>
