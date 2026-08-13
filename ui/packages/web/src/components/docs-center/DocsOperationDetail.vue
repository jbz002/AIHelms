<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { MarkdownRenderer, type HttpMethod, type Operation } from '@aihelms/shared'
import DocsParamsTable from './DocsParamsTable.vue'
import DocsSchemaTable from './DocsSchemaTable.vue'
import DocsTryItOut from './DocsTryItOut.vue'

interface Props {
  method: HttpMethod
  path: string
  operation: Operation
  docId: number
  libraryName: string
  baseUrl?: string
}
const props = defineProps<Props>()
const { t } = useI18n()

const METHOD_COLOR: Record<HttpMethod, string> = {
  get: 'bg-green-50 text-green-700 ring-green-200',
  post: 'bg-blue-50 text-blue-700 ring-blue-200',
  put: 'bg-amber-50 text-amber-700 ring-amber-200',
  delete: 'bg-red-50 text-red-700 ring-red-200',
  patch: 'bg-purple-50 text-purple-700 ring-purple-200',
}

const paramCount = computed(() => props.operation.parameters?.length ?? 0)
const jsonBody = computed(() => props.operation.requestBody?.content?.['application/json'])
const responses = computed(() => Object.entries(props.operation.responses ?? {}))

const tabs = computed(() => [
  { key: 'overview', label: t('docs.op.tab.overview') },
  {
    key: 'params',
    label: paramCount.value
      ? `${t('docs.op.tab.params')} (${paramCount.value})`
      : t('docs.op.tab.params'),
  },
  { key: 'body', label: t('docs.op.tab.body') },
  { key: 'response', label: `${t('docs.op.tab.response')} (${responses.value.length})` },
  { key: 'debug', label: t('docs.op.tab.debug') },
])
const activeTab = ref('overview')

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
      <!-- 概览：文档化拼接 参数 + 请求体 + 响应 -->
      <div v-if="activeTab === 'overview'" class="space-y-4">
        <div class="space-y-3">
          <h3 v-if="operation.summary" class="text-base font-semibold text-slate-900">{{ operation.summary }}</h3>
          <MarkdownRenderer v-if="operation.description" :content="operation.description" />
          <p v-else class="text-sm text-slate-400">{{ t('docs.op.noDesc') }}</p>
          <div v-if="operation.tags?.length" class="flex flex-wrap gap-1">
            <span
              v-for="tag in operation.tags"
              :key="tag"
              class="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500"
            >{{ tag }}</span>
          </div>
        </div>

        <section v-if="paramCount">
          <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{{ t('docs.op.tab.params') }}</div>
          <DocsParamsTable :parameters="operation.parameters ?? []" />
        </section>

        <section v-if="operation.requestBody && jsonBody?.schema">
          <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{{ t('docs.op.tab.body') }}</div>
          <DocsSchemaTable :schema="jsonBody.schema" />
        </section>

        <section v-if="responses.length">
          <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{{ t('docs.op.tab.response') }}</div>
          <div class="space-y-2">
            <div v-for="[code, resp] in responses" :key="code" class="rounded-md border border-slate-100 p-2">
              <div class="mb-1 flex items-center gap-2">
                <span
                  class="inline-flex justify-center rounded px-1.5 py-0.5 font-mono text-xs font-semibold ring-1 ring-inset"
                  :class="statusClass(code)"
                >{{ code }}</span>
                <span v-if="resp.description" class="text-xs text-slate-500">{{ resp.description }}</span>
              </div>
              <DocsSchemaTable v-if="resp.content?.['application/json']?.schema" :schema="resp.content['application/json'].schema!" />
            </div>
          </div>
        </section>
      </div>

      <!-- 参数 -->
      <div v-else-if="activeTab === 'params'">
        <DocsParamsTable :parameters="operation.parameters ?? []" />
      </div>

      <!-- 请求体 -->
      <div v-else-if="activeTab === 'body'" class="space-y-2">
        <template v-if="operation.requestBody">
          <div class="flex items-center gap-2 text-xs">
            <span class="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">application/json</span>
            <span v-if="operation.requestBody.required" class="text-red-500">{{ t('docs.op.col.required') }}</span>
          </div>
          <p v-if="operation.requestBody.description" class="text-sm text-slate-500">{{ operation.requestBody.description }}</p>
          <DocsSchemaTable v-if="jsonBody?.schema" :schema="jsonBody.schema" />
          <p v-else class="py-4 text-center text-sm text-slate-300">{{ t('docs.op.noBodySchema') }}</p>
        </template>
        <p v-else class="py-6 text-center text-sm text-slate-300">{{ t('docs.op.noBody') }}</p>
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
            <DocsSchemaTable v-if="resp.content?.['application/json']?.schema" :schema="resp.content['application/json'].schema!" />
          </div>
        </template>
        <p v-else class="py-6 text-center text-sm text-slate-300">{{ t('docs.op.noResponse') }}</p>
      </div>

      <!-- 调试 -->
      <div v-else-if="activeTab === 'debug'">
        <DocsTryItOut
          :key="`${method}-${path}`"
          :method="method"
          :path="path"
          :operation="operation"
          :doc-id="docId"
          :library-name="libraryName"
          :default-base-url="baseUrl"
        />
      </div>
    </div>
  </div>
</template>
