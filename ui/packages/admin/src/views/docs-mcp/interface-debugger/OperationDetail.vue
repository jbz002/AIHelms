<script setup lang="ts">
import { computed, ref } from 'vue'
import { MarkdownRenderer, type HttpMethod, type Operation, type Parameter } from '@aihelms/shared'
import SchemaTree from './SchemaTree.vue'
import TryItOut from './TryItOut.vue'

interface Props {
  method: HttpMethod
  path: string
  operation: Operation
  docId: number
}
const props = defineProps<Props>()

const METHOD_COLOR: Record<HttpMethod, string> = {
  get: 'bg-green-50 text-green-700 ring-green-200',
  post: 'bg-blue-50 text-blue-700 ring-blue-200',
  put: 'bg-amber-50 text-amber-700 ring-amber-200',
  delete: 'bg-red-50 text-red-700 ring-red-200',
  patch: 'bg-purple-50 text-purple-700 ring-purple-200',
}

type ParamGroup = 'path' | 'query' | 'header'

const paramsByIn = computed(() => {
  const groups: Record<ParamGroup, Parameter[]> = { path: [], query: [], header: [] }
  for (const p of props.operation.parameters ?? []) {
    if (p.in === 'path' || p.in === 'query' || p.in === 'header') groups[p.in].push(p)
  }
  return groups
})
const paramCount = computed(() => props.operation.parameters?.length ?? 0)
const jsonBody = computed(() => props.operation.requestBody?.content?.['application/json'])
const responses = computed(() => Object.entries(props.operation.responses ?? {}))

const tabs = computed(() => [
  { key: 'overview', label: '概览' },
  { key: 'params', label: `参数${paramCount.value ? ` (${paramCount.value})` : ''}` },
  { key: 'body', label: '请求体' },
  { key: 'response', label: `响应 (${responses.value.length})` },
  { key: 'debug', label: '调试' },
])
const activeTab = ref('overview')

function paramType(p: Parameter): string {
  const t = p.schema?.type
  if (!t) return ''
  return Array.isArray(t) ? t.join(' | ') : String(t)
}
function statusClass(code: string): string {
  const n = Number(code)
  if (Number.isNaN(n)) return 'bg-slate-100 text-slate-700'
  if (n >= 200 && n < 300) return 'bg-green-50 text-green-700 ring-green-200'
  if (n >= 300 && n < 500) return 'bg-amber-50 text-amber-700 ring-amber-200'
  return 'bg-red-50 text-red-700 ring-red-200'
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- 标题 -->
    <div class="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
      <span
        class="inline-flex shrink-0 justify-center rounded px-2 py-0.5 font-mono text-xs font-semibold ring-1 ring-inset"
        :class="METHOD_COLOR[method]"
      >{{ method.toUpperCase() }}</span>
      <span class="truncate font-mono text-sm font-medium text-slate-800">{{ path }}</span>
      <span v-if="operation.operationId" class="ml-auto shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">{{ operation.operationId }}</span>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 border-b border-slate-100 px-4">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="-mb-px border-b-2 px-3 py-2.5 text-sm font-medium transition-colors"
        :class="
          activeTab === tab.key
            ? 'border-purple-500 text-purple-600'
            : 'border-transparent text-slate-500 hover:text-slate-700'
        "
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-4 text-sm">
      <!-- 概览 -->
      <div v-if="activeTab === 'overview'" class="space-y-3">
        <h3 v-if="operation.summary" class="text-base font-semibold text-slate-900">{{ operation.summary }}</h3>
        <MarkdownRenderer v-if="operation.description" :content="operation.description" />
        <p v-else class="text-sm text-slate-400">无描述</p>
        <div v-if="operation.tags?.length" class="flex flex-wrap gap-1">
          <span
            v-for="tag in operation.tags"
            :key="tag"
            class="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500"
          >{{ tag }}</span>
        </div>
      </div>

      <!-- 参数 -->
      <div v-else-if="activeTab === 'params'" class="space-y-4">
        <template v-if="paramCount">
          <section v-for="grp in (['path', 'query', 'header'] as ParamGroup[])" :key="grp">
            <div v-if="paramsByIn[grp].length" class="mb-2">
              <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{{ grp === 'path' ? '路径参数' : grp === 'query' ? '查询参数' : '请求头' }}</div>
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
                    <tr v-for="p in paramsByIn[grp]" :key="p.name">
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
        </template>
        <p v-else class="py-6 text-center text-sm text-slate-300">该接口无参数</p>
      </div>

      <!-- 请求体 -->
      <div v-else-if="activeTab === 'body'" class="space-y-2">
        <template v-if="operation.requestBody">
          <div class="flex items-center gap-2 text-xs">
            <span class="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">application/json</span>
            <span v-if="operation.requestBody.required" class="text-red-500">必填</span>
          </div>
          <p v-if="operation.requestBody.description" class="text-sm text-slate-500">{{ operation.requestBody.description }}</p>
          <div v-if="jsonBody?.schema" class="rounded-md bg-slate-50 p-2">
            <SchemaTree :schema="jsonBody.schema" />
          </div>
          <p v-else class="py-4 text-center text-sm text-slate-300">请求体未定义结构</p>
        </template>
        <p v-else class="py-6 text-center text-sm text-slate-300">该接口无请求体</p>
      </div>

      <!-- 响应 -->
      <div v-else-if="activeTab === 'response'" class="space-y-3">
        <template v-if="responses.length">
          <div v-for="[code, resp] in responses" :key="code" class="rounded-md border border-slate-100 p-2">
            <div class="mb-1 flex items-center gap-2">
              <span
                class="inline-flex justify-center rounded px-1.5 py-0.5 font-mono text-xs font-semibold ring-1 ring-inset"
                :class="statusClass(code)"
              >{{ code }}</span>
              <span v-if="resp.description" class="text-xs text-slate-500">{{ resp.description }}</span>
            </div>
            <div v-if="resp.content?.['application/json']?.schema" class="rounded bg-slate-50 p-2">
              <SchemaTree :schema="resp.content['application/json'].schema!" />
            </div>
          </div>
        </template>
        <p v-else class="py-6 text-center text-sm text-slate-300">该接口未定义响应</p>
      </div>

      <!-- 调试 -->
      <div v-else-if="activeTab === 'debug'">
        <TryItOut
          :key="`${method}-${path}`"
          :method="method"
          :path="path"
          :operation="operation"
          :doc-id="docId"
        />
      </div>
    </div>
  </div>
</template>
