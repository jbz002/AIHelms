<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, Copy, Plug, RefreshCw, X } from 'lucide-vue-next'
import { getAdminMcpStatus, toast, copyText, type AdminMcpStatus } from '@aihelms/shared'

type Level = 'green' | 'yellow' | 'red' | 'grey'
type CopyTarget = 'endpoint' | 'json'

const status = ref<AdminMcpStatus | null>(null)
const isLoading = ref(false)
const isError = ref(false)
const dialogOpen = ref(false)
const copiedKey = ref<CopyTarget | null>(null)
const triggerRef = ref<HTMLElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)

const level = computed<Level>(() => {
  if (isError.value || (status.value !== null && status.value.tool_count === 0)) return 'red'
  if (status.value === null) return 'grey'
  return status.value.has_active_api_key ? 'green' : 'yellow'
})

const levelText = computed(
  () => ({ green: '已连通', yellow: '缺密钥', red: '异常', grey: '检查中' })[level.value],
)
const dotClass = computed(
  () =>
    (
      {
        green: 'bg-emerald-500',
        yellow: 'bg-amber-500',
        red: 'bg-rose-500',
        grey: 'bg-slate-300',
      } as const
    )[level.value],
)

const jsonConfig = computed(() =>
  JSON.stringify(
    {
      mcpServers: {
        'aihelms-admin': {
          url: status.value?.endpoint_url ?? '',
          headers: { Authorization: 'Bearer ak-你的平台APIKey' },
        },
      },
    },
    null,
    2,
  ),
)

async function fetchStatus(): Promise<void> {
  isLoading.value = true
  isError.value = false
  try {
    status.value = await getAdminMcpStatus()
  } catch {
    isError.value = true
    status.value = null
  } finally {
    isLoading.value = false
  }
}

async function recheck(): Promise<void> {
  await fetchStatus()
  if (level.value === 'green') toast.success('内置 MCP 已就绪')
  else if (level.value === 'yellow') toast.warning('工具已就绪，但暂无可用 API Key')
  else toast.error('内置 MCP 状态异常')
}

function toggleDialog(): void {
  dialogOpen.value = !dialogOpen.value
  if (dialogOpen.value && status.value === null && !isLoading.value) void fetchStatus()
}

function handleOutsideClick(event: MouseEvent): void {
  if (!dialogOpen.value) return
  const target = event.target as Node | null
  if (triggerRef.value?.contains(target as Node)) return
  if (panelRef.value?.contains(target as Node)) return
  dialogOpen.value = false
}

function handleEsc(event: KeyboardEvent): void {
  if (event.key === 'Escape' && dialogOpen.value) dialogOpen.value = false
}

async function copy(text: string, key: CopyTarget): Promise<void> {
  try {
    await copyText(text)
    copiedKey.value = key
    toast.success('已复制')
    setTimeout(() => {
      copiedKey.value = null
    }, 1500)
  } catch {
    toast.error('复制失败')
  }
}

onMounted(() => {
  void fetchStatus()
  document.addEventListener('mousedown', handleOutsideClick)
  document.addEventListener('keydown', handleEsc)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleOutsideClick)
  document.removeEventListener('keydown', handleEsc)
})
</script>

<template>
  <div class="relative">
    <button
      ref="triggerRef"
      type="button"
      :title="`内置管理员 MCP · ${levelText}`"
      class="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-slate-600 transition-colors hover:bg-slate-100/80"
      @click="toggleDialog"
    >
      <Plug class="h-4 w-4 text-slate-500" />
      <span class="h-2 w-2 rounded-full" :class="dotClass" />
      <span class="hidden sm:inline">内置 MCP</span>
    </button>

    <Teleport to="body">
      <div v-if="dialogOpen" class="fixed inset-0 z-50 bg-black/20" />
      <div
        v-if="dialogOpen"
        ref="panelRef"
        class="fixed right-4 top-16 z-50 w-[calc(100vw-2rem)] max-w-lg rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl"
      >
      <div class="mb-4 flex items-center justify-between">
        <h3 class="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <span class="h-2.5 w-2.5 rounded-full" :class="dotClass" />
          内置管理员 MCP · {{ levelText }}
        </h3>
        <button
          type="button"
          class="rounded-md p-1 text-slate-400 hover:bg-slate-100"
          @click="dialogOpen = false"
        >
          <X class="h-5 w-5" />
        </button>
      </div>

      <dl class="space-y-3 text-sm">
        <div>
          <dt class="mb-0.5 text-slate-500">接入端点</dt>
          <dd class="flex items-center gap-2">
            <code class="flex-1 truncate rounded bg-slate-50 px-2 py-1 text-slate-700">{{
              status?.endpoint_url || '—'
            }}</code>
            <button
              type="button"
              class="rounded p-1.5 text-slate-500 hover:bg-slate-100"
              title="复制端点"
              @click="copy(status?.endpoint_url ?? '', 'endpoint')"
            >
              <Check v-if="copiedKey === 'endpoint'" class="h-4 w-4 text-emerald-600" />
              <Copy v-else class="h-4 w-4" />
            </button>
          </dd>
        </div>
        <div class="flex flex-wrap gap-x-6 gap-y-2">
          <div>
            <dt class="text-slate-500">传输</dt>
            <dd class="text-slate-700">{{ status?.transport || '—' }}</dd>
          </div>
          <div>
            <dt class="text-slate-500">鉴权</dt>
            <dd class="text-slate-700">{{ status?.auth_scheme || '—' }}</dd>
          </div>
          <div>
            <dt class="text-slate-500">工具数</dt>
            <dd class="text-slate-700">{{ status?.tool_count ?? '—' }}</dd>
          </div>
          <div>
            <dt class="text-slate-500">可用 Key</dt>
            <dd class="text-slate-700">{{ status?.has_active_api_key ? '有' : '无' }}</dd>
          </div>
        </div>
      </dl>

      <ol class="mt-4 list-decimal space-y-1 pl-5 text-sm text-slate-600">
        <li>在 MCP 客户端按下述配置接入</li>
        <li>连接后工具以 <code class="rounded bg-slate-50 px-1">admin_</code> 前缀列出</li>
      </ol>

      <div class="mt-3">
        <div class="mb-1 flex items-center justify-between">
          <span class="text-sm text-slate-500">配置示例（Cursor / Claude Desktop 等）</span>
          <button
            type="button"
            class="rounded p-1.5 text-slate-500 hover:bg-slate-100"
            title="复制 JSON"
            @click="copy(jsonConfig, 'json')"
          >
            <Check v-if="copiedKey === 'json'" class="h-4 w-4 text-emerald-600" />
            <Copy v-else class="h-4 w-4" />
          </button>
        </div>
        <pre class="max-h-44 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">{{
          jsonConfig
        }}</pre>
      </div>

      <div class="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
        <p class="font-medium text-slate-700">API Key 获取指南</p>
        <ol class="mt-1 list-decimal space-y-0.5 pl-4">
          <li>
            进入「安全 → API Key」，点击新建，创建一个以
            <code class="rounded bg-white px-1">ak-</code> 开头的平台 API Key（权限等同管理员）。
          </li>
          <li>创建成功后立即复制完整 Key 值（仅展示一次，请妥善保存）。</li>
          <li>
            将 Key 粘贴到上方配置中替换
            <code class="rounded bg-white px-1">ak-你的平台APIKey</code> 占位符，填入客户端即可接入。
          </li>
        </ol>
      </div>

      <div class="mt-5 flex justify-end">
        <button
          type="button"
          :disabled="isLoading"
          class="flex items-center gap-1.5 rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-200 disabled:opacity-50"
          @click="recheck"
        >
          <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': isLoading }" />
          重新检查
        </button>
      </div>
      </div>
    </Teleport>
  </div>
</template>
