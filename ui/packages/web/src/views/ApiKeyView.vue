<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Copy, Check, Trash2, Plus, X, KeyRound } from 'lucide-vue-next'
import { getMyApiKeys, createMyApiKey, deleteMyApiKey, toast, type ApiKey } from '@aihelms/shared'
import { request } from '@aihelms/shared/src/api/request'

const keys = ref<ApiKey[]>([])
const loading = ref(false)
const mcpEndpoint = ref('')

const createDialogOpen = ref(false)
const createForm = ref({ name: '', description: '', expires_at: '' })
const createSubmitting = ref(false)

const justCreated = ref<ApiKey | null>(null)
const copied = ref(false)

async function loadKeys(): Promise<void> {
  loading.value = true
  try {
    const res = await getMyApiKeys(1, 50)
    keys.value = res.items
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  createForm.value = { name: '', description: '', expires_at: '' }
  createDialogOpen.value = true
}

async function submitCreate(): Promise<void> {
  if (!createForm.value.name.trim()) {
    toast.error('请填写名称')
    return
  }
  createSubmitting.value = true
  try {
    const result = await createMyApiKey({
      name: createForm.value.name.trim(),
      description: createForm.value.description,
      expires_at: createForm.value.expires_at
        ? new Date(createForm.value.expires_at).toISOString()
        : null,
    })
    createDialogOpen.value = false
    justCreated.value = result
    await loadKeys()
  } catch (e) {
    toast.error((e as { message?: string }).message || '创建失败')
  } finally {
    createSubmitting.value = false
  }
}

async function handleDelete(item: ApiKey): Promise<void> {
  if (!window.confirm(`确定删除 Key「${item.name}」？删除后使用此 Key 的客户端将无法接入。`)) return
  try {
    await deleteMyApiKey(item.id)
    if (justCreated.value?.id === item.id) justCreated.value = null
    await loadKeys()
    toast.success('已删除')
  } catch (e) {
    toast.error((e as { message?: string }).message || '删除失败')
  }
}

async function handleCopyRaw(): Promise<void> {
  if (!justCreated.value?.raw_key) return
  const text = justCreated.value.raw_key
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      if (!ok) throw new Error('execCommand copy failed')
    }
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {
    toast.error('复制失败')
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return iso.replace('T', ' ').slice(0, 19)
}

onMounted(async () => {
  await loadKeys()
  const webMcp = await request<{ endpoint_url: string }>('/api/v1/web-mcp', { silent: true }).catch(() => ({ endpoint_url: '' }))
  mcpEndpoint.value = webMcp.endpoint_url
})
</script>

<template>
  <div>
    <!-- 标题 -->
    <div class="mb-6 flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-slate-900">平台 API Key</h1>
        <p class="mt-1 text-sm text-slate-500">管理你自己的平台 API Key，用于本地 MCP 客户端接入 AIHelms 自助服务（与调模型的 AI Key 相互独立）</p>
      </div>
      <button
        class="flex items-center gap-1 rounded-lg bg-gradient-to-r from-purple-600 to-blue-600 px-4 py-2 text-sm font-medium text-white shadow-md shadow-purple-500/20 transition-all hover:from-purple-500 hover:to-blue-500 active:scale-[0.98]"
        @click="openCreate"
      >
        <Plus class="h-4 w-4" />
        新建 Key
      </button>
    </div>

    <!-- MCP 接入信息 -->
    <div v-if="mcpEndpoint" class="mb-6 rounded-xl border border-purple-100 bg-purple-50/50 p-4">
      <div class="flex items-center gap-2 text-sm font-medium text-purple-700">
        <KeyRound class="h-4 w-4" />
        MCP 接入信息
      </div>
      <div class="mt-2 text-xs text-slate-500">Endpoint</div>
      <code class="mt-0.5 block break-all rounded bg-white px-2 py-1 text-sm text-slate-800">{{ mcpEndpoint }}</code>
      <div class="mt-2 text-xs text-slate-500">鉴权头：<code class="text-slate-700">Authorization: Bearer &lt;你的平台 API Key&gt;</code></div>
    </div>

    <!-- 刚创建的明文（仅本次）-->
    <div v-if="justCreated" class="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4">
      <div class="flex items-center justify-between">
        <div class="text-sm font-medium text-amber-800">Key 已创建，请立即复制保存（关闭后不再显示明文）</div>
        <button class="text-amber-500 hover:text-amber-700" @click="justCreated = null">
          <X class="h-4 w-4" />
        </button>
      </div>
      <div class="mt-2 flex items-center gap-2">
        <code class="flex-1 break-all rounded bg-white px-2 py-1 text-sm text-amber-900">{{ justCreated.raw_key }}</code>
        <button
          class="shrink-0 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100"
          @click="handleCopyRaw"
        >
          <Check v-if="copied" class="inline h-3 w-3 text-green-600" />
          <Copy v-else class="inline h-3 w-3" />
          {{ copied ? '已复制' : '复制' }}
        </button>
      </div>
    </div>

    <!-- 列表 -->
    <div v-if="loading" class="py-12 text-center text-sm text-slate-500">加载中...</div>
    <div v-else-if="!keys.length" class="py-12 text-center text-sm text-slate-500">
      还没有 API Key，点击右上角「新建 Key」创建
    </div>
    <div v-else class="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table class="w-full text-sm">
        <thead class="bg-slate-50">
          <tr>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">名称</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">Key</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">状态</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">创建时间</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">最后使用</th>
            <th class="px-4 py-2.5 text-right font-medium text-slate-700">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in keys" :key="item.id" class="border-t border-slate-100">
            <td class="px-4 py-2.5">
              <div class="font-medium text-slate-900">{{ item.name }}</div>
              <div v-if="item.description" class="mt-0.5 text-xs text-slate-500">{{ item.description }}</div>
            </td>
            <td class="px-4 py-2.5">
              <code class="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-700">{{ item.key_prefix }}****</code>
            </td>
            <td class="px-4 py-2.5">
              <span v-if="item.is_active" class="rounded bg-green-50 px-2 py-0.5 text-xs text-green-700">启用</span>
              <span v-else class="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">禁用</span>
            </td>
            <td class="px-4 py-2.5 text-xs text-slate-500">{{ formatTime(item.created_at) }}</td>
            <td class="px-4 py-2.5 text-xs text-slate-500">{{ formatTime(item.last_used_at) }}</td>
            <td class="px-4 py-2.5 text-right">
              <button
                class="inline-flex items-center gap-1 rounded-lg bg-red-50 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
                @click="handleDelete(item)"
              >
                <Trash2 class="h-3 w-3" />
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 创建弹窗 -->
    <div
      v-if="createDialogOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
      @click.self="createDialogOpen = false"
    >
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">新建 API Key</h3>
        <div class="space-y-4">
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">名称<span class="ml-0.5 text-red-500">*</span></label>
            <input
              v-model="createForm.name"
              type="text"
              placeholder="如：my-agent"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">描述</label>
            <textarea
              v-model="createForm.description"
              rows="2"
              placeholder="可填写用途等信息"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
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
        </div>
        <div class="mt-6 flex justify-end gap-3">
          <button
            class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50"
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
</template>
