<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import {
  getMcpTools,
  refreshMcpTools,
  updateMcpToolMetadata,
  updateToolBilling,
  type McpTool,
  type UpdateToolMetadataParams,
} from '@aihelms/shared'
import { toast } from '@aihelms/shared'
import { RefreshCw, Settings, Shield, ChevronDown, ChevronRight } from 'lucide-vue-next'

interface Props {
  serverId: number | null
  serverBillingType: string
  /** false = 目录登记型：工具按人授权，平台不枚举，隐藏同步入口 */
  serverSyncToLitellm: boolean
}

const props = defineProps<Props>()

const tools = ref<McpTool[]>([])
const loading = ref(false)
const refreshing = ref(false)
const editingTool = ref<McpTool | null>(null)
const expandedTools = ref<Set<number>>(new Set())
const billingForm = ref({
  billing_type: 'per_call',
  internal_cost_per_call: 0,
  external_cost_per_call: 0,
  override: false,
})

const serverBillingFree = computed(() => props.serverBillingType === 'free')

watch(
  () => props.serverId,
  (v) => {
    if (v) loadTools()
    else tools.value = []
  },
  { immediate: true },
)

async function loadTools(): Promise<void> {
  if (!props.serverId) return
  loading.value = true
  try {
    tools.value = await getMcpTools(props.serverId)
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载工具失败')
  } finally {
    loading.value = false
  }
}

async function handleRefresh(): Promise<void> {
  if (!props.serverId) return
  refreshing.value = true
  try {
    tools.value = await refreshMcpTools(props.serverId)
    toast.success(`已同步 ${tools.value.length} 个工具`)
  } catch (e) {
    toast.error((e as { message?: string }).message || '同步失败')
  } finally {
    refreshing.value = false
  }
}

function toggleExpand(toolId: number): void {
  if (expandedTools.value.has(toolId)) {
    expandedTools.value.delete(toolId)
  } else {
    expandedTools.value.add(toolId)
  }
}

function openBillingDialog(tool: McpTool): void {
  editingTool.value = tool
  billingForm.value = {
    billing_type: tool.billing_type || 'per_call',
    internal_cost_per_call: Number(tool.internal_cost_per_call ?? 0),
    external_cost_per_call: Number(tool.external_cost_per_call ?? 0),
    override: tool.billing_type !== null,
  }
}

async function saveBilling(): Promise<void> {
  if (!editingTool.value) return
  try {
    if (billingForm.value.override) {
      await updateToolBilling(editingTool.value.id, {
        billing_type: billingForm.value.billing_type,
        internal_cost_per_call: billingForm.value.internal_cost_per_call,
        external_cost_per_call: billingForm.value.external_cost_per_call,
      })
    } else {
      await updateToolBilling(editingTool.value.id, {
        billing_type: undefined,
        internal_cost_per_call: undefined,
        external_cost_per_call: undefined,
      })
    }
    toast.success('计费配置已保存')
    editingTool.value = null
    await loadTools()
  } catch (e) {
    toast.error((e as { message?: string }).message || '保存失败')
  }
}

// ── P1 授权元数据（风险级 / 数据分级 / 审核状态 / 字段白名单）──
const metaTool = ref<McpTool | null>(null)
const metaSaving = ref(false)
const metaForm = ref({
  risk_level: 'read' as NonNullable<UpdateToolMetadataParams['risk_level']>,
  data_classification: 'internal' as NonNullable<UpdateToolMetadataParams['data_classification']>,
  review_status: 'approved' as NonNullable<UpdateToolMetadataParams['review_status']>,
  fields_allowlist: '',
})

const RISK_LABEL: Record<string, string> = {
  read: '只读',
  write: '写',
  sensitive: '敏感',
  destructive: '破坏性',
}
const REVIEW_LABEL: Record<string, string> = {
  pending: '待审',
  rejected: '已驳回',
  approved: '已审',
}

function riskBadgeClass(level: string): string {
  if (level === 'read') return 'bg-slate-100 text-slate-600'
  if (level === 'write') return 'bg-amber-50 text-amber-700'
  return 'bg-red-50 text-red-700'
}

function openMetaDialog(tool: McpTool): void {
  metaTool.value = tool
  metaForm.value = {
    risk_level: tool.risk_level || 'read',
    data_classification: tool.data_classification || 'internal',
    review_status: tool.review_status || 'approved',
    fields_allowlist: (tool.fields_allowlist || []).join(', '),
  }
}

async function saveMeta(): Promise<void> {
  if (!metaTool.value || !props.serverId) return
  const fields = metaForm.value.fields_allowlist
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  metaSaving.value = true
  try {
    await updateMcpToolMetadata(props.serverId, metaTool.value.id, {
      risk_level: metaForm.value.risk_level,
      data_classification: metaForm.value.data_classification,
      review_status: metaForm.value.review_status,
      fields_allowlist: fields.length ? fields : null,
    })
    toast.success('授权元数据已保存')
    metaTool.value = null
    await loadTools()
  } catch (e) {
    toast.error((e as { message?: string }).message || '保存失败')
  } finally {
    metaSaving.value = false
  }
}

function effectiveBilling(tool: McpTool): { type: string; internal: number; external: number; inherited: boolean } {
  if (tool.billing_type) {
    return {
      type: tool.billing_type,
      internal: Number(tool.internal_cost_per_call ?? 0),
      external: Number(tool.external_cost_per_call ?? 0),
      inherited: false,
    }
  }
  return {
    type: props.serverBillingType,
    internal: 0,
    external: 0,
    inherited: true,
  }
}
</script>

<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h3 class="text-sm font-semibold text-slate-900">工具列表（{{ tools.length }}）</h3>
      <button
        v-if="serverSyncToLitellm"
        class="flex items-center gap-1.5 rounded-md bg-purple-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-purple-500 disabled:opacity-50"
        :disabled="refreshing || !serverId"
        @click="handleRefresh"
      >
        <RefreshCw class="h-3 w-3" :class="refreshing ? 'animate-spin' : ''" />
        {{ refreshing ? '同步中...' : '同步工具' }}
      </button>
    </div>

    <div v-if="loading" class="py-8 text-center text-sm text-slate-500">加载中...</div>
    <div v-else-if="!serverSyncToLitellm" class="py-8 text-center text-sm text-slate-500">
      目录登记型 MCP：工具按人授权，用户在消费端（如新世纪AI助手）连接后可见，平台不枚举工具面。
    </div>
    <div v-else-if="tools.length === 0" class="py-8 text-center text-sm text-slate-500">
      暂无工具，点击「同步工具」获取
    </div>
    <div v-else class="space-y-2">
      <div
        v-for="tool in tools"
        :key="tool.id"
        class="overflow-hidden rounded-lg border border-slate-200 bg-white"
      >
        <!-- 行头 -->
        <div class="flex items-center gap-3 px-3 py-2.5">
          <button
            class="shrink-0 rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            @click="toggleExpand(tool.id)"
          >
            <ChevronDown v-if="expandedTools.has(tool.id)" class="h-4 w-4" />
            <ChevronRight v-else class="h-4 w-4" />
          </button>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="font-mono text-sm font-medium text-slate-900">{{ tool.tool_name }}</span>
              <span
                v-if="tool.billing_type"
                class="rounded bg-purple-50 px-1.5 py-0.5 text-[10px] text-purple-700"
              >
                独立计费
              </span>
              <span v-else class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                继承 Server
              </span>
              <span
                class="rounded px-1.5 py-0.5 text-[10px]"
                :class="riskBadgeClass(tool.risk_level)"
                :title="`风险级：${RISK_LABEL[tool.risk_level] || tool.risk_level}`"
              >
                {{ RISK_LABEL[tool.risk_level] || tool.risk_level }}
              </span>
              <span
                v-if="tool.review_status !== 'approved'"
                class="rounded px-1.5 py-0.5 text-[10px]"
                :class="tool.review_status === 'pending' ? 'bg-amber-50 text-amber-700' : 'bg-red-50 text-red-700'"
              >
                {{ REVIEW_LABEL[tool.review_status] || tool.review_status }}
              </span>
            </div>
            <p class="mt-0.5 truncate text-xs text-slate-500">
              {{ tool.description || '无描述' }}
            </p>
          </div>
          <div class="shrink-0 text-right text-xs">
            <template v-if="effectiveBilling(tool).type === 'free'">
              <span class="text-green-600">免费</span>
            </template>
            <template v-else>
              <span class="text-slate-700">
                ¥{{ effectiveBilling(tool).internal }} / ¥{{ effectiveBilling(tool).external }}
              </span>
              <span class="ml-1 text-[10px] text-slate-400">内/外</span>
            </template>
          </div>
          <button
            class="shrink-0 rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            title="授权元数据（风险级 / 审核）"
            @click="openMetaDialog(tool)"
          >
            <Shield class="h-3.5 w-3.5" />
          </button>
          <button
            class="shrink-0 rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            title="计费配置"
            @click="openBillingDialog(tool)"
          >
            <Settings class="h-3.5 w-3.5" />
          </button>
        </div>

        <!-- 展开详情 -->
        <div v-if="expandedTools.has(tool.id)" class="border-t border-slate-100 bg-slate-50 px-3 py-2.5">
          <div class="mb-2">
            <span class="text-xs font-medium text-slate-600">说明：</span>
            <p class="mt-1 whitespace-pre-wrap text-xs text-slate-700">
              {{ tool.description || '该工具没有提供说明' }}
            </p>
          </div>
          <div v-if="tool.input_schema && Object.keys(tool.input_schema).length > 0">
            <span class="text-xs font-medium text-slate-600">参数 Schema：</span>
            <pre class="mt-1 max-h-40 overflow-auto rounded bg-white p-2 text-[10px] text-slate-700">{{ JSON.stringify(tool.input_schema, null, 2) }}</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- 授权元数据对话框（P1） -->
    <div v-if="metaTool" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-1 text-lg font-semibold text-slate-900">{{ metaTool.tool_name }}</h3>
        <p class="mb-4 font-mono text-xs text-slate-500">{{ metaTool.tool_key || '—' }}</p>

        <div class="space-y-3">
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">风险级</label>
            <select v-model="metaForm.risk_level" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none">
              <option value="read">只读（可公共开放）</option>
              <option value="write">写</option>
              <option value="sensitive">敏感</option>
              <option value="destructive">破坏性</option>
            </select>
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">数据分级</label>
            <select v-model="metaForm.data_classification" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none">
              <option value="public">公开</option>
              <option value="internal">内部</option>
              <option value="confidential">机密</option>
              <option value="secret">绝密</option>
            </select>
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">审核状态</label>
            <select v-model="metaForm.review_status" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none">
              <option value="approved">已通过（参与授权编译）</option>
              <option value="pending">待审核（不参与编译）</option>
              <option value="rejected">已驳回（不参与编译）</option>
            </select>
            <p class="mt-1 text-[11px] text-slate-400">工具定义（名称/描述/入参）变化时会自动回到待审核。</p>
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">字段白名单（逗号分隔，留空 = 不限）</label>
            <input
              v-model="metaForm.fields_allowlist"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
              placeholder="例如：supplier_name, order_no"
            />
            <p class="mt-1 text-[11px] text-slate-400">仅登记与展示用；真正的字段裁剪由业务系统执行。</p>
          </div>
        </div>

        <div class="mt-6 flex justify-end gap-3">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200" @click="metaTool = null">
            取消
          </button>
          <button
            class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            :disabled="metaSaving"
            @click="saveMeta"
          >
            {{ metaSaving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Tool billing dialog -->
    <div
      v-if="editingTool"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
    >
      <div
        class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl"
      >
        <h3 class="mb-4 text-lg font-semibold text-slate-900">
          {{ editingTool.tool_name }} - 计费配置
        </h3>

        <div class="mb-4 flex items-center gap-2">
          <input
            id="override"
            v-model="billingForm.override"
            type="checkbox"
            class="h-4 w-4 rounded border-slate-300"
          />
          <label for="override" class="text-sm text-slate-700">
            为此工具配置独立计费（不勾选则继承 Server 级配置：{{ serverBillingFree ? '免费' : '按次计费' }}）
          </label>
        </div>

        <div v-if="billingForm.override" class="space-y-3">
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">计费方式</label>
            <select
              v-model="billingForm.billing_type"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            >
              <option value="per_call">按次计费</option>
              <option value="free">免费</option>
            </select>
          </div>
          <div v-if="billingForm.billing_type !== 'free'">
            <label class="mb-1 block text-sm font-medium text-slate-700">内部单价（每次）</label>
            <input
              v-model.number="billingForm.internal_cost_per_call"
              type="number"
              step="0.000001"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div v-if="billingForm.billing_type !== 'free'">
            <label class="mb-1 block text-sm font-medium text-slate-700">外部单价（每次）</label>
            <input
              v-model.number="billingForm.external_cost_per_call"
              type="number"
              step="0.000001"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
        </div>

        <div class="mt-6 flex justify-end gap-3">
          <button
            class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-200"
            @click="editingTool = null"
          >
            取消
          </button>
          <button
            class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-purple-700"
            @click="saveBilling"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
