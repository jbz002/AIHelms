<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createMcpGrant,
  createMcpToolset,
  deleteMcpToolset,
  getAllDepartments,
  getMcpServers,
  getMcpTools,
  getRoles,
  getUsers,
  listMcpGrants,
  listMcpToolsets,
  reconcileMcpAuthz,
  revokeMcpGrant,
  toast,
  usePermission,
  type CreateMcpGrantParams,
  type FullDepartmentItem,
  type GrantEffect,
  type GrantSubjectType,
  type GrantTargetType,
  type McpGrant,
  type McpReconcileResult,
  type McpServer,
  type McpTool,
  type McpToolset,
  type McpToolsetItem,
  type Role,
  type User,
} from '@aihelms/shared'
import { Plus, Trash2, ShieldCheck, Layers, Users } from 'lucide-vue-next'
import ConfirmDialog from '../../components/ConfirmDialog.vue'

const { hasPermission } = usePermission()

const tab = ref<'grants' | 'toolsets'>('grants')
const loading = ref(false)
const saving = ref(false)

const grants = ref<McpGrant[]>([])
const toolsets = ref<McpToolset[]>([])
const servers = ref<McpServer[]>([])
const roles = ref<Role[]>([])
const departments = ref<FullDepartmentItem[]>([])
const userOptions = ref<User[]>([])
const userKeyword = ref('')

const subjectFilter = ref<GrantSubjectType | ''>('')

const grantDialog = ref(false)
const grantForm = ref({
  subject_type: 'role' as GrantSubjectType,
  subject_id: null as number | null,
  target_type: 'server' as GrantTargetType,
  target_id: null as number | null,
  effect: 'allow' as GrantEffect,
  reason: '',
  expires_at: '',
})

const toolsetDialog = ref(false)
const toolsetForm = ref({ name: '', description: '' })
const toolsetPick = ref<{ serverId: number | null; tools: McpTool[]; picked: string[] }>({
  serverId: null,
  tools: [],
  picked: [],
})
const toolsetItems = ref<McpToolsetItem[]>([])
const confirm = ref<{ open: boolean; message: string; action: (() => void) | null }>({
  open: false,
  message: '',
  action: null,
})

const reconcileResult = ref<McpReconcileResult | null>(null)

const canEdit = computed(() => hasPermission('mcp:update'))
const canDelete = computed(() => hasPermission('mcp:delete'))

const serverName = computed(() => {
  const map = new Map<number, string>()
  for (const s of servers.value) map.set(s.id, s.server_name)
  return map
})
const toolsetName = computed(() => {
  const map = new Map<number, string>()
  for (const t of toolsets.value) map.set(t.id, t.name)
  return map
})
const roleName = computed(() => {
  const map = new Map<number, string>()
  for (const r of roles.value) map.set(r.id, r.display_name || r.name)
  return map
})
const deptName = computed(() => {
  const map = new Map<number, string>()
  for (const d of departments.value) map.set(d.id, d.name)
  return map
})
const userMap = computed(() => {
  const map = new Map<number, string>()
  for (const u of userOptions.value) map.set(u.id, u.display_name || u.username)
  return map
})

const filteredGrants = computed(() =>
  subjectFilter.value
    ? grants.value.filter((g) => g.subject_type === subjectFilter.value)
    : grants.value,
)

function subjectLabel(grant: McpGrant): string {
  if (grant.subject_type === 'public') return '所有人（公共）'
  const id = grant.subject_id ?? 0
  if (grant.subject_type === 'role') return `角色：${roleName.value.get(id) ?? `#${id}`}`
  if (grant.subject_type === 'dept') return `部门：${deptName.value.get(id) ?? `#${id}`}`
  return `用户：${userMap.value.get(id) ?? `#${id}`}`
}

function targetLabel(grant: McpGrant): string {
  if (grant.target_type === 'toolset') {
    return `工具束：${toolsetName.value.get(grant.target_id) ?? `#${grant.target_id}`}`
  }
  return `Server：${serverName.value.get(grant.target_id) ?? `#${grant.target_id}`}`
}

async function loadAll(): Promise<void> {
  loading.value = true
  try {
    const [serverPage, grantRes, toolsetRes, roleList, deptList] = await Promise.all([
      getMcpServers(1, 200),
      listMcpGrants(),
      listMcpToolsets(),
      getRoles(),
      getAllDepartments(),
    ])
    servers.value = serverPage.items
    grants.value = grantRes.items
    toolsets.value = toolsetRes.items
    roles.value = roleList
    departments.value = deptList
    await loadUsers()
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载授权数据失败')
  } finally {
    loading.value = false
  }
}

async function loadUsers(): Promise<void> {
  try {
    const res = await getUsers(1, 50, userKeyword.value || undefined)
    userOptions.value = res.items
  } catch {
    userOptions.value = []
  }
}

function openGrantDialog(): void {
  grantForm.value = {
    subject_type: 'role',
    subject_id: roles.value.length === 1 ? roles.value[0].id : null,
    target_type: 'server',
    target_id: null,
    effect: 'allow',
    reason: '',
    expires_at: '',
  }
  grantDialog.value = true
}

async function submitGrant(): Promise<void> {
  const form = grantForm.value
  if (form.subject_type !== 'public' && !form.subject_id) {
    toast.error('请选择授权主体')
    return
  }
  if (!form.target_id) {
    toast.error('请选择授权目标')
    return
  }
  if (form.effect === 'deny' && form.target_type === 'toolset') {
    toast.error('P1 只支持 Server 级 deny')
    return
  }
  const params: CreateMcpGrantParams = {
    subject_type: form.subject_type,
    subject_id: form.subject_type === 'public' ? null : form.subject_id,
    target_type: form.target_type,
    target_id: form.target_id,
    effect: form.effect,
    reason: form.reason || undefined,
    expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
  }
  saving.value = true
  try {
    const res = await createMcpGrant(params)
    toast.success(
      res.sync.mode === 'compiled'
        ? `授权已生效（重编译 ${res.sync.applied ?? 0} 把 Key）`
        : '授权已登记（编译器关闭，未下发）',
    )
    grantDialog.value = false
    await loadAll()
  } catch (e) {
    toast.error((e as { message?: string }).message || '授权失败')
  } finally {
    saving.value = false
  }
}

function askRevoke(grant: McpGrant): void {
  confirm.value = {
    open: true,
    message: `确认撤销「${subjectLabel(grant)} → ${targetLabel(grant)}」？撤销后该主体将立即失去这部分访问。`,
    action: async () => {
      try {
        await revokeMcpGrant(grant.id)
        toast.success('授权已撤销')
        await loadAll()
      } catch (e) {
        toast.error((e as { message?: string }).message || '撤销失败')
      }
    },
  }
}

async function runReconcile(mode: 'check' | 'apply'): Promise<void> {
  try {
    const res = await reconcileMcpAuthz(mode)
    reconcileResult.value = res
    if (res.drift === 0 && res.errors === 0) {
      toast.success(`对账通过：${res.keys} 把 Key 与网关一致`)
    } else if (mode === 'apply') {
      toast.success(`已按平台为准修复 ${res.fixed} 把 Key（原漂移 ${res.drift}）`)
    } else {
      toast.warning(`发现 ${res.drift} 把 Key 与网关不一致`)
    }
  } catch (e) {
    toast.error((e as { message?: string }).message || '对账失败')
  }
}

// ── 工具束 ────────────────────────────────────────────────────────────────

function openToolsetDialog(): void {
  toolsetForm.value = { name: '', description: '' }
  toolsetPick.value = { serverId: null, tools: [], picked: [] }
  toolsetItems.value = []
  toolsetDialog.value = true
}

async function loadPickerTools(): Promise<void> {
  if (!toolsetPick.value.serverId) {
    toolsetPick.value.tools = []
    return
  }
  try {
    toolsetPick.value.tools = await getMcpTools(toolsetPick.value.serverId)
    toolsetPick.value.picked = []
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载工具失败')
  }
}

function addPickedTools(): void {
  const serverId = toolsetPick.value.serverId
  if (!serverId || toolsetPick.value.picked.length === 0) return
  for (const toolName of toolsetPick.value.picked) {
    const exists = toolsetItems.value.some(
      (i) => i.server_id === serverId && i.tool_name === toolName,
    )
    if (!exists) toolsetItems.value.push({ server_id: serverId, tool_name: toolName })
  }
  toolsetPick.value.picked = []
}

function removeToolsetItem(index: number): void {
  toolsetItems.value.splice(index, 1)
}

function toolsetItemLabel(item: McpToolsetItem): string {
  return `${serverName.value.get(item.server_id) ?? `#${item.server_id}`}.${item.tool_name}`
}

async function submitToolset(): Promise<void> {
  if (!toolsetForm.value.name.trim()) {
    toast.error('请填写工具束名称')
    return
  }
  if (toolsetItems.value.length === 0) {
    toast.error('请至少选择一个工具')
    return
  }
  saving.value = true
  try {
    await createMcpToolset({
      name: toolsetForm.value.name.trim(),
      description: toolsetForm.value.description,
      items: toolsetItems.value,
    })
    toast.success('工具束已创建')
    toolsetDialog.value = false
    await loadAll()
  } catch (e) {
    toast.error((e as { message?: string }).message || '创建失败')
  } finally {
    saving.value = false
  }
}

function askDeleteToolset(toolset: McpToolset): void {
  confirm.value = {
    open: true,
    message: `确认删除工具束「${toolset.name}」？仍有生效授权引用时会被拒绝。`,
    action: async () => {
      try {
        await deleteMcpToolset(toolset.id)
        toast.success('工具束已删除')
        await loadAll()
      } catch (e) {
        toast.error((e as { message?: string }).message || '删除失败')
      }
    },
  }
}

function runConfirm(): void {
  const action = confirm.value.action
  confirm.value.open = false
  action?.()
}

onMounted(loadAll)
</script>

<template>
  <div class="mx-auto max-w-6xl space-y-5 p-6">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900">MCP 授权中心</h1>
        <p class="mt-1 text-sm text-slate-500">
          授权矩阵是唯一事实源：谁（人 / 部门 / 角色 / 公共）能用哪个 Server 或工具束。
          变更即重编译受影响的 Key 并下发网关。
        </p>
      </div>
      <div class="flex items-center gap-2">
        <button
          class="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-50"
          @click="runReconcile('check')"
        >
          <ShieldCheck class="h-4 w-4" /> 对账检查
        </button>
        <button
          v-if="tab === 'grants' && canEdit"
          class="flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-purple-500"
          @click="openGrantDialog"
        >
          <Plus class="h-4 w-4" /> 新增授权
        </button>
        <button
          v-if="tab === 'toolsets' && canEdit"
          class="flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-purple-500"
          @click="openToolsetDialog"
        >
          <Plus class="h-4 w-4" /> 新建工具束
        </button>
      </div>
    </header>

    <div
      v-if="reconcileResult"
      class="flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 text-sm"
      :class="
        reconcileResult.drift === 0 && reconcileResult.errors === 0
          ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
          : 'border-amber-200 bg-amber-50 text-amber-900'
      "
    >
      <span>
        对账（{{ reconcileResult.mode }}）：{{ reconcileResult.keys }} 把 Key，
        漂移 {{ reconcileResult.drift }}，错误 {{ reconcileResult.errors }}
        <template v-if="reconcileResult.mode === 'apply'">
          ，已修复 {{ reconcileResult.fixed }}
        </template>
      </span>
      <button
        v-if="reconcileResult.drift > 0 && reconcileResult.mode === 'check' && canEdit"
        class="rounded-md border border-amber-300 bg-white px-2 py-1 text-xs text-amber-800 hover:bg-amber-100"
        @click="runReconcile('apply')"
      >
        以平台为准修复
      </button>
      <button class="ml-auto text-xs text-slate-500 hover:text-slate-700" @click="reconcileResult = null">
        收起
      </button>
    </div>

    <div class="flex items-center gap-1 border-b border-slate-200">
      <button
        class="flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm"
        :class="tab === 'grants' ? 'border-purple-600 font-medium text-purple-700' : 'border-transparent text-slate-500 hover:text-slate-700'"
        @click="tab = 'grants'"
      >
        <Users class="h-4 w-4" /> 授权矩阵（{{ grants.length }}）
      </button>
      <button
        class="flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm"
        :class="tab === 'toolsets' ? 'border-purple-600 font-medium text-purple-700' : 'border-transparent text-slate-500 hover:text-slate-700'"
        @click="tab = 'toolsets'"
      >
        <Layers class="h-4 w-4" /> 工具束（{{ toolsets.length }}）
      </button>
    </div>

    <div v-if="loading" class="py-12 text-center text-sm text-slate-500">加载中...</div>

    <template v-else-if="tab === 'grants'">
      <div class="flex items-center gap-2">
        <label class="text-xs text-slate-500">按主体筛选</label>
        <select
          v-model="subjectFilter"
          class="rounded-md border border-slate-200 px-2 py-1 text-sm focus:border-purple-400 focus:outline-none"
        >
          <option value="">全部</option>
          <option value="public">公共</option>
          <option value="role">角色</option>
          <option value="dept">部门</option>
          <option value="user">用户</option>
        </select>
      </div>

      <div v-if="filteredGrants.length === 0" class="rounded-xl border border-dashed border-slate-200 py-12 text-center text-sm text-slate-500">
        还没有授权。新增一条后，受影响的 Key 会立即重编译并下发。
      </div>

      <div v-else class="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th class="px-4 py-2.5 font-medium">主体</th>
              <th class="px-4 py-2.5 font-medium">目标</th>
              <th class="px-4 py-2.5 font-medium">效果</th>
              <th class="px-4 py-2.5 font-medium">理由</th>
              <th class="px-4 py-2.5 font-medium">过期</th>
              <th class="px-4 py-2.5 font-medium">创建时间</th>
              <th class="px-4 py-2.5 font-medium"></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="grant in filteredGrants" :key="grant.id" class="hover:bg-slate-50/60">
              <td class="px-4 py-2.5 text-slate-800">{{ subjectLabel(grant) }}</td>
              <td class="px-4 py-2.5 font-mono text-xs text-slate-700">{{ targetLabel(grant) }}</td>
              <td class="px-4 py-2.5">
                <span
                  class="rounded px-1.5 py-0.5 text-[11px]"
                  :class="grant.effect === 'deny' ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700'"
                >
                  {{ grant.effect === 'deny' ? '拒绝' : '允许' }}
                </span>
              </td>
              <td class="max-w-[16rem] truncate px-4 py-2.5 text-xs text-slate-500" :title="grant.reason || ''">
                {{ grant.reason || '—' }}
              </td>
              <td class="px-4 py-2.5 text-xs text-slate-500">{{ grant.expires_at ? grant.expires_at.slice(0, 10) : '长期' }}</td>
              <td class="px-4 py-2.5 text-xs text-slate-500">{{ grant.created_at ? grant.created_at.slice(0, 16).replace('T', ' ') : '—' }}</td>
              <td class="px-4 py-2.5 text-right">
                <button
                  v-if="canEdit"
                  class="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                  title="撤销授权"
                  @click="askRevoke(grant)"
                >
                  <Trash2 class="h-4 w-4" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <template v-else>
      <div v-if="toolsets.length === 0" class="rounded-xl border border-dashed border-slate-200 py-12 text-center text-sm text-slate-500">
        还没有工具束。工具束把跨 Server 的若干工具打包，供角色/部门整束授权。
      </div>
      <div v-else class="grid gap-3 md:grid-cols-2">
        <div v-for="toolset in toolsets" :key="toolset.id" class="rounded-xl border border-slate-200 bg-white p-4">
          <div class="flex items-start justify-between gap-2">
            <div>
              <h3 class="font-mono text-sm font-semibold text-slate-900">{{ toolset.name }}</h3>
              <p class="mt-0.5 text-xs text-slate-500">{{ toolset.description || '无描述' }}</p>
            </div>
            <button
              v-if="canDelete"
              class="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
              title="删除工具束"
              @click="askDeleteToolset(toolset)"
            >
              <Trash2 class="h-4 w-4" />
            </button>
          </div>
          <ul class="mt-3 space-y-1">
            <li v-for="item in toolset.items" :key="`${item.server_id}.${item.tool_name}`" class="font-mono text-xs text-slate-600">
              {{ serverName.get(item.server_id) ?? `#${item.server_id}` }}.{{ item.tool_name }}
            </li>
          </ul>
        </div>
      </div>
    </template>

    <!-- 新增授权 -->
    <div v-if="grantDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-4">
      <div class="w-full max-w-lg rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">新增授权</h3>
        <div class="space-y-3">
          <div class="grid grid-cols-2 gap-3">
            <label class="block text-sm">
              <span class="mb-1 block text-xs text-slate-500">主体类型</span>
              <select v-model="grantForm.subject_type" class="w-full rounded-md border border-slate-200 px-2 py-1.5">
                <option value="public">所有人（公共）</option>
                <option value="role">角色</option>
                <option value="dept">部门</option>
                <option value="user">用户</option>
              </select>
            </label>
            <label v-if="grantForm.subject_type === 'role'" class="block text-sm">
              <span class="mb-1 block text-xs text-slate-500">角色</span>
              <select v-model="grantForm.subject_id" class="w-full rounded-md border border-slate-200 px-2 py-1.5">
                <option :value="null">请选择</option>
                <option v-for="role in roles" :key="role.id" :value="role.id">{{ role.display_name || role.name }}</option>
              </select>
            </label>
            <label v-else-if="grantForm.subject_type === 'dept'" class="block text-sm">
              <span class="mb-1 block text-xs text-slate-500">部门</span>
              <select v-model="grantForm.subject_id" class="w-full rounded-md border border-slate-200 px-2 py-1.5">
                <option :value="null">请选择</option>
                <option v-for="dept in departments" :key="dept.id" :value="dept.id">{{ dept.name }}</option>
              </select>
            </label>
            <label v-else-if="grantForm.subject_type === 'user'" class="block text-sm">
              <span class="mb-1 block text-xs text-slate-500">用户（按关键词搜索）</span>
              <div class="flex gap-1">
                <input
                  v-model="userKeyword"
                  class="min-w-0 flex-1 rounded-md border border-slate-200 px-2 py-1.5"
                  placeholder="用户名/邮箱"
                  @keyup.enter="loadUsers"
                />
                <button class="rounded-md border border-slate-200 px-2 text-xs text-slate-600" @click="loadUsers">搜索</button>
              </div>
              <select v-model="grantForm.subject_id" class="mt-1 w-full rounded-md border border-slate-200 px-2 py-1.5">
                <option :value="null">请选择</option>
                <option v-for="user in userOptions" :key="user.id" :value="user.id">
                  {{ user.display_name || user.username }}（{{ user.username }}）
                </option>
              </select>
            </label>
            <div v-else class="text-xs text-slate-500">
              公共授权 = 所有 Key 都获得该目标（仅用于只读目录类）。
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <label class="block text-sm">
              <span class="mb-1 block text-xs text-slate-500">目标类型</span>
              <select v-model="grantForm.target_type" class="w-full rounded-md border border-slate-200 px-2 py-1.5">
                <option value="server">MCP Server</option>
                <option value="toolset">工具束</option>
              </select>
            </label>
            <label v-if="grantForm.target_type === 'server'" class="block text-sm">
              <span class="mb-1 block text-xs text-slate-500">Server</span>
              <select v-model="grantForm.target_id" class="w-full rounded-md border border-slate-200 px-2 py-1.5">
                <option :value="null">请选择</option>
                <option v-for="server in servers" :key="server.id" :value="server.id">
                  {{ server.server_name }}（{{ server.name }}）
                </option>
              </select>
            </label>
            <label v-else class="block text-sm">
              <span class="mb-1 block text-xs text-slate-500">工具束</span>
              <select v-model="grantForm.target_id" class="w-full rounded-md border border-slate-200 px-2 py-1.5">
                <option :value="null">请选择</option>
                <option v-for="toolset in toolsets" :key="toolset.id" :value="toolset.id">{{ toolset.name }}</option>
              </select>
            </label>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <label class="block text-sm">
              <span class="mb-1 block text-xs text-slate-500">效果</span>
              <select v-model="grantForm.effect" class="w-full rounded-md border border-slate-200 px-2 py-1.5">
                <option value="allow">允许</option>
                <option value="deny">拒绝（优先）</option>
              </select>
            </label>
            <label class="block text-sm">
              <span class="mb-1 block text-xs text-slate-500">过期时间（留空 = 长期）</span>
              <input v-model="grantForm.expires_at" type="datetime-local" class="w-full rounded-md border border-slate-200 px-2 py-1.5" />
            </label>
          </div>

          <label class="block text-sm">
            <span class="mb-1 block text-xs text-slate-500">理由（进策略变更审计）</span>
            <input v-model="grantForm.reason" class="w-full rounded-md border border-slate-200 px-2 py-1.5" placeholder="例如：采购部日常工作需要" />
          </label>
        </div>
        <div class="mt-5 flex justify-end gap-3">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="grantDialog = false">取消</button>
          <button
            class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-500 disabled:opacity-50"
            :disabled="saving"
            @click="submitGrant"
          >
            {{ saving ? '提交中...' : '提交' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 新建工具束 -->
    <div v-if="toolsetDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-4">
      <div class="w-full max-w-2xl rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">新建工具束</h3>
        <div class="grid gap-3 md:grid-cols-2">
          <label class="block text-sm">
            <span class="mb-1 block text-xs text-slate-500">名称（建议英文/下划线）</span>
            <input v-model="toolsetForm.name" class="w-full rounded-md border border-slate-200 px-2 py-1.5" placeholder="procurement_readonly" />
          </label>
          <label class="block text-sm">
            <span class="mb-1 block text-xs text-slate-500">描述</span>
            <input v-model="toolsetForm.description" class="w-full rounded-md border border-slate-200 px-2 py-1.5" placeholder="采购只读" />
          </label>
        </div>

        <div class="mt-4 rounded-xl border border-slate-200 p-3">
          <div class="flex flex-wrap items-end gap-2">
            <label class="text-sm">
              <span class="mb-1 block text-xs text-slate-500">Server</span>
              <select v-model="toolsetPick.serverId" class="rounded-md border border-slate-200 px-2 py-1.5" @change="loadPickerTools">
                <option :value="null">请选择</option>
                <option v-for="server in servers" :key="server.id" :value="server.id">{{ server.server_name }}</option>
              </select>
            </label>
            <label class="min-w-[16rem] flex-1 text-sm">
              <span class="mb-1 block text-xs text-slate-500">工具（可多选）</span>
              <select v-model="toolsetPick.picked" multiple class="h-24 w-full rounded-md border border-slate-200 px-2 py-1">
                <option v-for="tool in toolsetPick.tools" :key="tool.id" :value="tool.tool_name">
                  {{ tool.tool_name }}{{ tool.review_status !== 'approved' ? '（待审）' : '' }}
                </option>
              </select>
            </label>
            <button class="rounded-md border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50" @click="addPickedTools">
              加入
            </button>
          </div>

          <div v-if="toolsetItems.length" class="mt-3 flex flex-wrap gap-1.5">
            <span
              v-for="(item, index) in toolsetItems"
              :key="`${item.server_id}.${item.tool_name}`"
              class="flex items-center gap-1 rounded bg-slate-100 px-2 py-1 font-mono text-[11px] text-slate-700"
            >
              {{ toolsetItemLabel(item) }}
              <button class="text-slate-400 hover:text-red-600" @click="removeToolsetItem(index)">×</button>
            </span>
          </div>
          <p v-else class="mt-3 text-xs text-slate-400">还没有选择工具</p>
        </div>

        <div class="mt-5 flex justify-end gap-3">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="toolsetDialog = false">取消</button>
          <button
            class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-500 disabled:opacity-50"
            :disabled="saving"
            @click="submitToolset"
          >
            {{ saving ? '提交中...' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :visible="confirm.open"
      title="确认操作"
      :message="confirm.message"
      @confirm="runConfirm"
      @cancel="confirm.open = false"
    />
  </div>
</template>
