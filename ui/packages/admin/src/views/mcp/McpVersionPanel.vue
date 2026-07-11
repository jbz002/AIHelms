<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  getMcpServerVersions,
  createMcpServerVersion,
  activateMcpServerVersion,
  deprecateMcpServerVersion,
  toast,
  usePermission,
  type McpServer,
  type McpServerVersion,
} from '@aihelms/shared'
import { Plus, GitBranch, CheckCircle2, AlertTriangle, Archive } from 'lucide-vue-next'
import ConfirmDialog from '../../components/ConfirmDialog.vue'

interface Props {
  serverId: number
  activeVersion?: McpServerVersion | null
}
const props = defineProps<Props>()
const emit = defineEmits<{
  activated: [server: McpServer]
}>()

const { hasPermission } = usePermission()
const canManage = hasPermission('mcp:update') || hasPermission('mcp:create')

const versions = ref<McpServerVersion[]>([])
const loading = ref(false)
const actingId = ref<number | null>(null)
const showCreate = ref(false)
const deprecateTarget = ref<McpServerVersion | null>(null)

const transportLabels: Record<string, string> = {
  sse: 'SSE',
  http: 'HTTP',
  streamable_http: 'Streamable HTTP',
  streamableHttp: 'Streamable HTTP',
}

const form = ref({
  version: '',
  version_label: '',
  url: '',
  transport: 'sse',
  auth_type: 'none',
  change_log: '',
})

async function loadVersions(): Promise<void> {
  if (!props.serverId) return
  loading.value = true
  try {
    versions.value = await getMcpServerVersions(props.serverId, true)
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载版本失败')
  } finally {
    loading.value = false
  }
}

watch(() => props.serverId, loadVersions, { immediate: true })

async function handleActivate(v: McpServerVersion): Promise<void> {
  actingId.value = v.id
  try {
    const server = await activateMcpServerVersion(props.serverId, v.id)
    toast.success(v.is_active ? '已是当前版本' : `已激活版本 ${v.version}`)
    emit('activated', server)
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '激活失败')
  } finally {
    actingId.value = null
  }
}

async function confirmDeprecate(): Promise<void> {
  if (!deprecateTarget.value) return
  const target = deprecateTarget.value
  actingId.value = target.id
  try {
    await deprecateMcpServerVersion(props.serverId, target.id)
    toast.success(`已弃用版本 ${target.version}`)
    deprecateTarget.value = null
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '弃用失败')
  } finally {
    actingId.value = null
  }
}

function openCreate(): void {
  form.value = {
    version: '',
    version_label: '',
    url: props.activeVersion?.url || '',
    transport: props.activeVersion?.transport || 'sse',
    auth_type: props.activeVersion?.auth_type || 'none',
    change_log: '',
  }
  showCreate.value = true
}

async function handleCreate(): Promise<void> {
  if (!form.value.version.trim() || !form.value.url.trim()) {
    toast.error('请填写版本号和 URL')
    return
  }
  try {
    await createMcpServerVersion(props.serverId, {
      version: form.value.version.trim(),
      version_label: form.value.version_label.trim(),
      url: form.value.url.trim(),
      transport: form.value.transport,
      auth_type: form.value.auth_type,
      change_log: form.value.change_log.trim(),
    })
    toast.success('版本创建成功（未激活，不影响线上）')
    showCreate.value = false
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '创建失败')
  }
}

function lifecycleBadge(s: string): { cls: string; label: string; icon: typeof CheckCircle2 } {
  if (s === 'active') return { cls: 'bg-green-50 text-green-600', label: '生效中', icon: CheckCircle2 }
  if (s === 'deprecated') return { cls: 'bg-slate-100 text-slate-400 line-through', label: '已弃用', icon: Archive }
  return { cls: 'bg-amber-50 text-amber-600', label: '灰度', icon: AlertTriangle }
}
</script>

<template>
  <div class="rounded-xl border border-slate-200/60 p-3">
    <div class="mb-2 flex items-center justify-between">
      <h4 class="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
        <GitBranch class="h-4 w-4 text-purple-500" /> 版本管理
      </h4>
      <button
        v-if="canManage"
        class="flex items-center gap-1 rounded-md bg-purple-50 px-2 py-1 text-xs font-medium text-purple-600 transition-colors hover:bg-purple-100"
        @click="openCreate"
      >
        <Plus class="h-3 w-3" /> 新版本
      </button>
    </div>

    <div v-if="loading" class="py-4 text-center text-xs text-slate-400">加载中...</div>
    <div v-else-if="versions.length === 0" class="py-4 text-center text-xs text-slate-400">暂无版本</div>
    <div v-else class="space-y-1.5">
      <div
        v-for="v in versions"
        :key="v.id"
        class="flex items-center gap-2 rounded-lg border border-slate-100 px-2.5 py-2 text-xs"
      >
        <component :is="lifecycleBadge(v.lifecycle_status).icon" class="h-3.5 w-3.5 shrink-0 text-slate-400" />
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-1.5">
            <span class="font-mono font-medium text-slate-800">v{{ v.version }}</span>
            <span v-if="v.version_label" class="truncate text-slate-400">{{ v.version_label }}</span>
          </div>
          <div class="mt-0.5 truncate text-slate-400">
            {{ transportLabels[v.transport] || v.transport }} · {{ v.url }}
          </div>
        </div>
        <span class="shrink-0 rounded px-1.5 py-0.5 text-[10px]" :class="lifecycleBadge(v.lifecycle_status).cls">
          {{ lifecycleBadge(v.lifecycle_status).label }}
        </span>
        <div v-if="canManage" class="flex shrink-0 gap-1">
          <button
            v-if="!v.is_active"
            class="rounded bg-green-50 px-1.5 py-0.5 text-[10px] text-green-600 hover:bg-green-100 disabled:opacity-50"
            :disabled="actingId === v.id"
            @click="handleActivate(v)"
          >
            {{ actingId === v.id ? '...' : v.lifecycle_status === 'deprecated' ? '回滚' : '激活' }}
          </button>
          <button
            v-if="!v.is_active && v.lifecycle_status !== 'deprecated'"
            class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-200"
            @click="deprecateTarget = v"
          >
            弃用
          </button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :visible="!!deprecateTarget"
      title="弃用版本"
      :message="`确认弃用版本 ${deprecateTarget?.version}？弃用版本永不可被 Key 调用。`"
      @confirm="confirmDeprecate"
      @cancel="deprecateTarget = null"
    />

    <div
      v-if="showCreate"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
    >
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">创建新版本</h3>
        <div class="mb-3 grid grid-cols-2 gap-3">
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-600">版本号</label>
            <input v-model="form.version" placeholder="如 2.0.0" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-600">标签（可选）</label>
            <input v-model="form.version_label" placeholder="如 2026-07 灰度" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none" />
          </div>
        </div>
        <div class="mb-3">
          <label class="mb-1 block text-xs font-medium text-slate-600">URL</label>
          <input v-model="form.url" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none" />
        </div>
        <div class="mb-3 grid grid-cols-2 gap-3">
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-600">传输方式</label>
            <select v-model="form.transport" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none">
              <option value="sse">SSE</option>
              <option value="http">HTTP</option>
              <option value="streamableHttp">Streamable HTTP</option>
            </select>
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-600">认证方式</label>
            <select v-model="form.auth_type" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none">
              <option value="none">无</option>
              <option value="bearer">Bearer</option>
              <option value="basic">Basic</option>
              <option value="custom">Custom</option>
            </select>
          </div>
        </div>
        <div class="mb-4">
          <label class="mb-1 block text-xs font-medium text-slate-600">变更说明</label>
          <textarea v-model="form.change_log" rows="2" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none" />
        </div>
        <div class="flex justify-end gap-3">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="showCreate = false">取消</button>
          <button class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700" @click="handleCreate">创建</button>
        </div>
      </div>
    </div>
  </div>
</template>
