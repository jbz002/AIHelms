<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  getAgents,
  getAgentCategories,
  getAgentPlatforms,
  createAgentCategory,
  deleteAgentCategory,
  createAgentPlatform,
  deleteAgentPlatform,
  deleteAgent,
  type Agent,
  type AgentCategory,
  type AgentPlatform,
} from '@aihelms/shared'
import { toast, usePermission } from '@aihelms/shared'
import { Plus, X } from 'lucide-vue-next'
import HostedIcon from '@aihelms/shared/src/components/HostedIcon.vue'
import ConfirmDialog from '../../components/ConfirmDialog.vue'

const { hasPermission } = usePermission()
const router = useRouter()

const agents = ref<Agent[]>([])
const categories = ref<AgentCategory[]>([])
const platforms = ref<AgentPlatform[]>([])
const loading = ref(false)
const selectedCategory = ref<string | null>(null)
const selectedPlatform = ref<string | null>(null)
const selectedAgent = ref<Agent | null>(null)

const showCategoryForm = ref(false)
const categoryFormName = ref('')
const showPlatformForm = ref(false)
const platformFormName = ref('')
const platformFormLabel = ref('')

const deleteCategoryTarget = ref<AgentCategory | null>(null)
const deletePlatformTarget = ref<AgentPlatform | null>(null)
const deleteAgentTarget = ref<Agent | null>(null)

const categoriesWithCount = computed(() => {
  const counts = new Map<string, number>()
  for (const a of agents.value) counts.set(a.category, (counts.get(a.category) || 0) + 1)
  return categories.value.map((c) => ({ ...c, count: counts.get(c.name) || 0 }))
})

const platformsWithCount = computed(() => {
  const counts = new Map<string, number>()
  for (const a of agents.value) counts.set(a.platform, (counts.get(a.platform) || 0) + 1)
  return platforms.value.map((p) => ({ ...p, count: counts.get(p.name) || 0 }))
})

const filteredAgents = computed(() => {
  return agents.value.filter((a) => {
    if (selectedCategory.value && a.category !== selectedCategory.value) return false
    if (selectedPlatform.value && a.platform !== selectedPlatform.value) return false
    return true
  })
})

async function loadData(): Promise<void> {
  loading.value = true
  try {
    const [agentsRes, catsRes, platsRes] = await Promise.all([
      getAgents(1, 200),
      getAgentCategories(),
      getAgentPlatforms(),
    ])
    agents.value = agentsRes.items
    categories.value = catsRes
    platforms.value = platsRes
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  router.push('/agents/new')
}

function openEdit(agent: Agent): void {
  router.push(`/agents/${agent.id}`)
}

async function handleCreateCategory(): Promise<void> {
  if (!categoryFormName.value.trim()) {
    toast.error('请输入分类名称')
    return
  }
  try {
    await createAgentCategory({ name: categoryFormName.value.trim() })
    toast.success('分类创建成功')
    showCategoryForm.value = false
    categoryFormName.value = ''
    await loadData()
  } catch (e) {
    toast.error((e as { message?: string }).message || '创建失败')
  }
}

async function handleCreatePlatform(): Promise<void> {
  if (!platformFormLabel.value.trim()) {
    toast.error('请输入平台名称')
    return
  }
  try {
    const label = platformFormLabel.value.trim()
    await createAgentPlatform({
      name: label,
      label: label,
    })
    toast.success('平台创建成功')
    showPlatformForm.value = false
    platformFormName.value = ''
    platformFormLabel.value = ''
    await loadData()
  } catch (e) {
    toast.error((e as { message?: string }).message || '创建失败')
  }
}

async function confirmDeleteCategory(): Promise<void> {
  if (!deleteCategoryTarget.value) return
  try {
    await deleteAgentCategory(deleteCategoryTarget.value.id)
    toast.success('分类删除成功')
    if (selectedCategory.value === deleteCategoryTarget.value.name) selectedCategory.value = null
    deleteCategoryTarget.value = null
    await loadData()
  } catch (e) {
    toast.error((e as { message?: string }).message || '删除失败')
  }
}

async function confirmDeletePlatform(): Promise<void> {
  if (!deletePlatformTarget.value) return
  try {
    await deleteAgentPlatform(deletePlatformTarget.value.id)
    toast.success('平台删除成功')
    if (selectedPlatform.value === deletePlatformTarget.value.name) selectedPlatform.value = null
    deletePlatformTarget.value = null
    await loadData()
  } catch (e) {
    toast.error((e as { message?: string }).message || '删除失败')
  }
}

async function confirmDeleteAgent(): Promise<void> {
  if (!deleteAgentTarget.value) return
  try {
    await deleteAgent(deleteAgentTarget.value.id)
    toast.success('智能体删除成功')
    if (selectedAgent.value?.id === deleteAgentTarget.value.id) selectedAgent.value = null
    deleteAgentTarget.value = null
    await loadData()
  } catch (e) {
    toast.error((e as { message?: string }).message || '删除失败')
  }
}

function statusColor(status: string): string {
  if (status === 'online') return 'bg-green-50 text-green-600'
  if (status === 'offline') return 'bg-slate-100 text-slate-500'
  return 'bg-amber-50 text-amber-600'
}

function getPlatformLabel(name: string): string {
  return platforms.value.find((p) => p.name === name)?.label || name
}

onMounted(loadData)
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="flex flex-1 gap-4 overflow-hidden">
      <!-- 左栏：列表 -->
      <div class="flex w-80 shrink-0 flex-col overflow-hidden rounded-2xl border border-slate-200/60 bg-white shadow-sm">
        <div class="flex h-12 shrink-0 items-center justify-between border-b border-slate-200/60 px-4">
          <h3 class="text-sm font-semibold text-slate-900">智能体</h3>
          <button
            v-if="hasPermission('agent:create')"
            class="flex items-center gap-1 rounded-md bg-purple-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-purple-700"
            @click="openCreate"
          >
            <Plus class="h-3 w-3" /> 新建
          </button>
        </div>

        <!-- 分类导航 -->
        <div class="border-b border-slate-100 px-2 py-1.5">
          <div class="flex flex-wrap items-center gap-1">
            <button
              class="rounded-md px-3 py-1.5 text-xs font-medium"
              :class="!selectedCategory ? 'bg-purple-50 text-purple-700' : 'text-slate-500 hover:bg-slate-50'"
              @click="selectedCategory = null"
            >
              全部 ({{ agents.length }})
            </button>
            <div v-for="cat in categoriesWithCount" :key="cat.id" class="group flex items-center">
              <button
                class="rounded-md px-3 py-1.5 text-xs font-medium"
                :class="selectedCategory === cat.name ? 'bg-purple-50 text-purple-700' : 'text-slate-500 hover:bg-slate-50'"
                @click="selectedCategory = cat.name"
              >
                {{ cat.name }} ({{ cat.count }})
              </button>
              <button
                v-if="hasPermission('agent:delete')"
                class="ml-0.5 hidden text-slate-400 hover:text-red-500 group-hover:inline-block"
                @click="deleteCategoryTarget = cat"
              >
                <X class="h-3 w-3" />
              </button>
            </div>
            <button
              v-if="hasPermission('agent:create')"
              class="rounded-md px-2 py-1.5 text-xs text-purple-500 hover:text-purple-600"
              @click="showCategoryForm = true"
            >
              + 新建分类
            </button>
          </div>
        </div>

        <!-- 平台导航 -->
        <div class="border-b border-slate-100 px-2 py-1.5">
          <div class="flex flex-wrap items-center gap-1">
            <button
              class="rounded-md px-3 py-1.5 text-xs font-medium"
              :class="!selectedPlatform ? 'bg-blue-50 text-blue-700' : 'text-slate-500 hover:bg-slate-50'"
              @click="selectedPlatform = null"
            >
              全部平台
            </button>
            <div v-for="plat in platformsWithCount" :key="plat.id" class="group flex items-center">
              <button
                class="rounded-md px-3 py-1.5 text-xs font-medium"
                :class="selectedPlatform === plat.name ? 'bg-blue-50 text-blue-700' : 'text-slate-500 hover:bg-slate-50'"
                @click="selectedPlatform = plat.name"
              >
                {{ plat.label }} ({{ plat.count }})
              </button>
              <button
                v-if="hasPermission('agent:delete')"
                class="ml-0.5 hidden text-slate-400 hover:text-red-500 group-hover:inline-block"
                @click="deletePlatformTarget = plat"
              >
                <X class="h-3 w-3" />
              </button>
            </div>
            <button
              v-if="hasPermission('agent:create')"
              class="rounded-md px-2 py-1.5 text-xs text-blue-500 hover:text-blue-600"
              @click="showPlatformForm = true"
            >
              + 新建平台
            </button>
          </div>
        </div>

        <!-- 列表 -->
        <div class="flex-1 overflow-y-auto p-2">
          <div v-if="loading" class="py-10 text-center text-xs text-slate-400">加载中...</div>
          <div v-else-if="filteredAgents.length === 0" class="py-10 text-center text-xs text-slate-400">暂无智能体</div>
          <div
            v-for="agent in filteredAgents"
            v-else
            :key="agent.id"
            class="mb-1 flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 transition-colors"
            :class="selectedAgent?.id === agent.id ? 'bg-purple-50 ring-1 ring-purple-200' : 'hover:bg-slate-50'"
            @click="selectedAgent = agent"
          >
            <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100">
              <HostedIcon :src="agent.icon_url" :size="20" :alt="agent.name" />
            </div>
            <div class="min-w-0 flex-1">
              <span
                class="block truncate text-sm font-medium"
                :class="selectedAgent?.id === agent.id ? 'text-purple-700' : 'text-slate-900'"
              >
                {{ agent.name }}
              </span>
              <div class="mt-0.5 flex flex-wrap items-center gap-1">
                <span class="rounded bg-blue-50 px-1 py-0.5 text-[10px] text-blue-600">{{ getPlatformLabel(agent.platform) }}</span>
                <span v-if="agent.is_published" class="rounded bg-green-50 px-1 py-0.5 text-[10px] text-green-600">已发布</span>
                <span v-if="agent.requires_approval" class="rounded bg-amber-50 px-1 py-0.5 text-[10px] text-amber-600">需审批</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右栏：详情 -->
      <div class="flex flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200/60 bg-white shadow-sm">
        <template v-if="selectedAgent">
          <div class="flex h-12 shrink-0 items-center justify-between border-b border-slate-200/60 px-4">
            <div class="flex min-w-0 items-center gap-3">
              <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100">
                <HostedIcon :src="selectedAgent.icon_url" :size="20" :alt="selectedAgent.name" />
              </div>
              <h3 class="truncate text-sm font-semibold text-slate-900">{{ selectedAgent.name }}</h3>
              <span class="rounded px-1.5 py-0.5 text-[10px] font-medium" :class="statusColor(selectedAgent.status)">
                {{ selectedAgent.status }}
              </span>
              <span v-if="selectedAgent.is_published" class="rounded bg-green-50 px-1.5 py-0.5 text-[10px] text-green-600">已发布</span>
              <span v-if="selectedAgent.requires_approval" class="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600">需审批</span>
            </div>
            <div class="flex shrink-0 gap-1.5">
              <button
                v-if="hasPermission('agent:update')"
                class="rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200"
                @click="openEdit(selectedAgent)"
              >
                编辑
              </button>
              <button
                v-if="hasPermission('agent:delete')"
                class="rounded-md bg-red-50 px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-100"
                @click="deleteAgentTarget = selectedAgent"
              >
                删除
              </button>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto p-4">
            <div class="mb-4 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <div><span class="text-slate-500">平台：</span><span class="text-slate-700">{{ getPlatformLabel(selectedAgent.platform) }}</span></div>
              <div><span class="text-slate-500">分类：</span><span class="text-slate-700">{{ selectedAgent.category || '-' }}</span></div>
              <div><span class="text-slate-500">状态：</span><span class="text-slate-700">{{ selectedAgent.status }}</span></div>
              <div><span class="text-slate-500">使用人数：</span><span class="text-slate-700">{{ selectedAgent.user_count }}</span></div>
              <div><span class="text-slate-500">调用次数：</span><span class="text-slate-700">{{ selectedAgent.call_count }}</span></div>
              <div><span class="text-slate-500">创建时间：</span><span class="text-slate-700">{{ selectedAgent.created_at || '-' }}</span></div>
              <div class="col-span-2">
                <span class="text-slate-500">Chat URL：</span>
                <span class="break-all font-mono text-slate-700">{{ selectedAgent.chat_url || '-' }}</span>
              </div>
              <div v-if="selectedAgent.tags?.length" class="col-span-2">
                <span class="text-slate-500">标签：</span>
                <span
                  v-for="tag in selectedAgent.tags"
                  :key="tag"
                  class="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-slate-600"
                >{{ tag }}</span>
              </div>
            </div>
            <div class="mb-2 text-xs font-medium text-slate-500">描述</div>
            <p class="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
              {{ selectedAgent.description || '暂无描述' }}
            </p>
          </div>
        </template>
        <div v-else class="flex h-full items-center justify-center text-sm text-slate-400">
          请从左侧选择智能体查看详情
        </div>
      </div>
    </div>

    <!-- 新建分类弹窗 -->
    <div
      v-if="showCategoryForm"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
    >
      <div class="w-full max-w-sm rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">新建分类</h3>
        <input
          v-model="categoryFormName"
          class="mb-4 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
          placeholder="如：office / customer / hr"
        />
        <div class="flex justify-end gap-3">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200" @click="showCategoryForm = false">取消</button>
          <button class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700" @click="handleCreateCategory">创建</button>
        </div>
      </div>
    </div>

    <!-- 新建平台弹窗 -->
    <div
      v-if="showPlatformForm"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
    >
      <div class="w-full max-w-sm rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">新建平台</h3>
        <div class="mb-4">
          <label class="mb-1 block text-sm font-medium text-slate-700">平台名称</label>
          <input
            v-model="platformFormLabel"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            placeholder="如：Dify / Coze / 自研"
          />
        </div>
        <div class="flex justify-end gap-3">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200" @click="showPlatformForm = false">取消</button>
          <button class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700" @click="handleCreatePlatform">创建</button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :visible="!!deleteCategoryTarget"
      title="删除分类"
      :message="`确认删除分类 ${deleteCategoryTarget?.name}？该分类下的智能体不会被删除。`"
      @confirm="confirmDeleteCategory"
      @cancel="deleteCategoryTarget = null"
    />
    <ConfirmDialog
      :visible="!!deletePlatformTarget"
      title="删除平台"
      :message="`确认删除平台 ${deletePlatformTarget?.label}？该平台下的智能体不会被删除。`"
      @confirm="confirmDeletePlatform"
      @cancel="deletePlatformTarget = null"
    />
    <ConfirmDialog
      :visible="!!deleteAgentTarget"
      title="删除智能体"
      :message="`确认删除 ${deleteAgentTarget?.name}？此操作不可恢复。`"
      @confirm="confirmDeleteAgent"
      @cancel="deleteAgentTarget = null"
    />
  </div>
</template>
