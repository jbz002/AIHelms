<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Copy, Check } from 'lucide-vue-next'
import {
  getCliTokens,
  createCliToken,
  toggleCliToken,
  deleteCliToken,
  toast,
  usePermission,
  CLI_SCOPE_OPTIONS,
  type CliToken,
} from '@aihelms/shared'
import Pagination from '../../components/Pagination.vue'
import ConfirmDialog from '../../components/ConfirmDialog.vue'

const { hasPermission } = usePermission()

const tokens = ref<CliToken[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

interface CreateForm {
  name: string
  description: string
  owner_type: string
  owner_id: string
  scopes: string[]
  expires_at: string
}
const createDialogOpen = ref(false)
const createForm = ref<CreateForm>(emptyForm())
const createSubmitting = ref(false)
const createdToken = ref<CliToken | null>(null)
const copiedCreate = ref(false)

const deleteTarget = ref<CliToken | null>(null)

function emptyForm(): CreateForm {
  return {
    name: '',
    description: '',
    owner_type: 'user',
    owner_id: '',
    scopes: ['skill:search', 'skill:read', 'skill:install'],
    expires_at: '',
  }
}

async function loadTokens(): Promise<void> {
  loading.value = true
  try {
    const res = await getCliTokens(page.value, pageSize.value)
    tokens.value = res.items
    total.value = res.total
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载失败')
  } finally {
    loading.value = false
  }
}

function handlePageChange(p: number): void {
  page.value = p
  loadTokens()
}

function openCreateDialog(): void {
  createForm.value = emptyForm()
  createdToken.value = null
  createDialogOpen.value = true
}

function toggleScope(scope: string): void {
  const list = createForm.value.scopes
  const idx = list.indexOf(scope)
  if (idx >= 0) {
    list.splice(idx, 1)
  } else {
    list.push(scope)
  }
}

async function submitCreate(): Promise<void> {
  if (!createForm.value.name.trim()) {
    toast.error('请填写名称')
    return
  }
  if (!createForm.value.owner_id.trim()) {
    toast.error('请填写所有者 ID')
    return
  }
  createSubmitting.value = true
  try {
    const result = await createCliToken({
      name: createForm.value.name.trim(),
      description: createForm.value.description,
      owner_type: createForm.value.owner_type,
      owner_id: Number(createForm.value.owner_id),
      scopes: createForm.value.scopes,
      expires_at: createForm.value.expires_at
        ? new Date(createForm.value.expires_at).toISOString()
        : null,
    })
    createdToken.value = result
    await loadTokens()
  } catch (e) {
    toast.error((e as { message?: string }).message || '创建失败')
  } finally {
    createSubmitting.value = false
  }
}

async function handleCopyCreate(): Promise<void> {
  if (!createdToken.value?.key_value) return
  try {
    await navigator.clipboard.writeText(createdToken.value.key_value)
    copiedCreate.value = true
    setTimeout(() => {
      copiedCreate.value = false
    }, 2000)
  } catch {
    toast.error('复制失败')
  }
}

async function handleToggle(item: CliToken): Promise<void> {
  try {
    await toggleCliToken(item.id)
    await loadTokens()
  } catch (e) {
    toast.error((e as { message?: string }).message || '操作失败')
  }
}

async function handleConfirmDelete(): Promise<void> {
  if (!deleteTarget.value) return
  try {
    await deleteCliToken(deleteTarget.value.id)
    deleteTarget.value = null
    await loadTokens()
  } catch (e) {
    toast.error((e as { message?: string }).message || '删除失败')
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return iso.replace('T', ' ').slice(0, 19)
}

function isExpired(iso: string | null): boolean {
  if (!iso) return false
  return new Date(iso).getTime() < Date.now()
}

const ownerTypeLabel: Record<string, string> = {
  user: '用户',
  department: '部门',
  project: '项目',
}

onMounted(loadTokens)
</script>

<template>
  <div>
    <div class="mb-6 flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-slate-900">CLI 令牌</h1>
        <p class="mt-1 text-sm text-slate-500">
          管理 CLI 分发通道的 Scoped Token（sk_cli_ 前缀），供第三方 CLI 程序化接入
        </p>
      </div>
      <button
        v-if="hasPermission('cli_token:create')"
        class="rounded-lg bg-gradient-to-r from-purple-600 to-blue-600 px-4 py-2 text-sm font-medium text-white shadow-md shadow-purple-500/20 transition-all hover:from-purple-500 hover:to-blue-500 active:scale-[0.98]"
        @click="openCreateDialog"
      >
        新建 CLI 令牌
      </button>
    </div>

    <div v-if="loading" class="py-12 text-center text-sm text-slate-500">加载中...</div>
    <div v-else-if="tokens.length === 0" class="py-12 text-center text-sm text-slate-500">
      还没有 CLI 令牌
    </div>
    <div v-else class="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table class="w-full text-sm">
        <thead class="bg-slate-50">
          <tr>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">名称</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">Token</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">Scope</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">所有者</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">状态</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">最后使用</th>
            <th class="px-4 py-2.5 text-right font-medium text-slate-700">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in tokens" :key="item.id" class="border-t border-slate-100">
            <td class="px-4 py-2.5">
              <div class="font-medium text-slate-900">{{ item.name }}</div>
              <div v-if="item.description" class="mt-0.5 text-xs text-slate-500">
                {{ item.description }}
              </div>
            </td>
            <td class="px-4 py-2.5">
              <code class="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-700">
                {{ item.token_prefix }}****
              </code>
            </td>
            <td class="px-4 py-2.5">
              <div class="flex flex-wrap gap-1">
                <span
                  v-for="scope in item.scopes"
                  :key="scope"
                  class="rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-700"
                >
                  {{ scope }}
                </span>
              </div>
            </td>
            <td class="px-4 py-2.5 text-xs text-slate-600">
              {{ ownerTypeLabel[item.owner_type] || item.owner_type }} #{{ item.owner_id }}
            </td>
            <td class="px-4 py-2.5">
              <span
                v-if="isExpired(item.expires_at)"
                class="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700"
              >
                已过期
              </span>
              <span
                v-else-if="item.is_active"
                class="rounded bg-green-50 px-2 py-0.5 text-xs text-green-700"
              >
                启用
              </span>
              <span v-else class="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                禁用
              </span>
            </td>
            <td class="px-4 py-2.5 text-xs text-slate-500">{{ formatTime(item.last_used_at) }}</td>
            <td class="px-4 py-2.5 text-right">
              <div class="flex justify-end gap-2">
                <button
                  v-if="hasPermission('cli_token:update')"
                  class="rounded-lg px-3 py-1 text-xs font-medium"
                  :class="item.is_active
                    ? 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                    : 'bg-green-50 text-green-700 hover:bg-green-100'"
                  @click="handleToggle(item)"
                >
                  {{ item.is_active ? '禁用' : '启用' }}
                </button>
                <button
                  v-if="hasPermission('cli_token:delete')"
                  class="rounded-lg bg-red-50 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
                  @click="deleteTarget = item"
                >
                  撤销
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Pagination
      v-if="total > 0"
      :page="page"
      :page-size="pageSize"
      :total="total"
      @change="handlePageChange"
    />

    <!-- 创建弹窗 -->
    <div
      v-if="createDialogOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
      @click.self="createDialogOpen = false"
    >
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">新建 CLI 令牌</h3>

        <div v-if="createdToken" class="space-y-3">
          <div class="rounded-lg bg-green-50 border border-green-200 p-3">
            <p class="text-sm font-medium text-green-800">令牌创建成功，请立即复制保存（仅显示一次）</p>
            <code class="mt-2 block break-all rounded bg-white px-2 py-1 font-mono text-xs text-green-900">
              {{ createdToken.key_value }}
            </code>
            <button
              class="mt-2 inline-flex items-center gap-1 rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700"
              @click="handleCopyCreate"
            >
              <Check v-if="copiedCreate" class="h-3.5 w-3.5" />
              <Copy v-else class="h-3.5 w-3.5" />
              {{ copiedCreate ? '已复制' : '复制' }}
            </button>
          </div>
          <div class="flex justify-end">
            <button
              class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
              @click="createDialogOpen = false"
            >
              我已保存
            </button>
          </div>
        </div>

        <div v-else class="space-y-4">
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">名称<span class="ml-0.5 text-red-500">*</span></label>
            <input
              v-model="createForm.name"
              type="text"
              placeholder="如：clawhub-cli-分发"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">描述</label>
            <textarea
              v-model="createForm.description"
              rows="2"
              placeholder="可填写用途、对接人等信息"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">所有者类型</label>
              <select
                v-model="createForm.owner_type"
                class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
              >
                <option value="user">用户</option>
                <option value="department">部门</option>
                <option value="project">项目</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">所有者 ID<span class="ml-0.5 text-red-500">*</span></label>
              <input
                v-model="createForm.owner_id"
                type="number"
                placeholder="如：1"
                class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
              />
            </div>
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">Scope（分权）</label>
            <div class="flex flex-wrap gap-2">
              <label
                v-for="scope in CLI_SCOPE_OPTIONS"
                :key="scope"
                class="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs"
                :class="createForm.scopes.includes(scope) ? 'bg-indigo-50 border-indigo-300 text-indigo-700' : 'text-slate-600'"
              >
                <input
                  type="checkbox"
                  :checked="createForm.scopes.includes(scope)"
                  class="h-3 w-3"
                  @change="toggleScope(scope)"
                />
                {{ scope }}
              </label>
            </div>
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">过期时间</label>
            <input
              v-model="createForm.expires_at"
              type="datetime-local"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
            <p class="mt-1 text-xs text-slate-400">留空表示永不过期</p>
          </div>
          <div class="flex justify-end gap-3">
            <button
              class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
              :disabled="createSubmitting"
              @click="createDialogOpen = false"
            >
              取消
            </button>
            <button
              class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
              :disabled="createSubmitting"
              @click="submitCreate"
            >
              {{ createSubmitting ? '创建中...' : '创建' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :visible="!!deleteTarget"
      title="撤销 CLI 令牌"
      :message="deleteTarget ? `确定撤销令牌「${deleteTarget.name}」？撤销后使用此令牌的 CLI 将无法访问平台` : ''"
      confirm-text="撤销"
      @confirm="handleConfirmDelete"
      @cancel="deleteTarget = null"
    />
  </div>
</template>
