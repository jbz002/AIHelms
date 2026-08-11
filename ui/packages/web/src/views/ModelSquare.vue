<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { getMyKeys, CAPABILITY_LABELS, MODEL_CATEGORIES } from '@aihelms/shared'
import { request } from '@aihelms/shared/src/api/request'
import { createResourceApplication } from '@aihelms/shared/src/api/resource-application'
import type { AiKey } from '@aihelms/shared/src/types/ai-key'
import { Cpu, CheckCircle2, Search, X, MessageSquare, Box } from 'lucide-vue-next'
import ProviderIcon from '../components/ProviderIcon.vue'
import ModelAccessDialog from '../components/ModelAccessDialog.vue'

interface ModelItem {
  id: number
  name: string
  model_id: string
  category: string
  mode?: string | null
  capabilities: string[]
  description: string
  logo_provider_type: string
  icon_url: string
  is_published: boolean
  requires_approval: boolean
  deployment_count: number
  has_anthropic_deployment: boolean
  has_openai_deployment: boolean
}


const models = ref<ModelItem[]>([])
const myModels = ref<string[]>([])
const mainKeyValue = ref('')
const litellmBaseUrl = ref('')
const isLoading = ref(true)
const search = ref('')
const categoryFilter = ref('')
const capabilityFilter = ref('')
const showApplyDialog = ref(false)
const showAccessDialog = ref(false)
const activeModel = ref<ModelItem | null>(null)
const applyReason = ref('')
const applyingId = ref<number | null>(null)

const categories = computed(() => {
  const set = new Set(models.value.map(m => m.category).filter(Boolean))
  return Array.from(set).sort()
})

const capabilities = computed(() => {
  const set = new Set(models.value.flatMap(m => m.capabilities || []))
  return Array.from(set).sort()
})

// 能力枚举值 → 中文展示（capabilities 入库为英文 snake_case，UI 显示中文）
function capabilityLabel(cap: string): string {
  return CAPABILITY_LABELS[cap as keyof typeof CAPABILITY_LABELS] || cap
}

// 模型分类枚举值 → 中文展示（category 入库为英文 chat/embedding…，UI 显示中文）
function categoryLabel(cat: string): string {
  const found = MODEL_CATEGORIES.find(c => c.value === cat)
  return found ? found.label : cat
}

const filtered = computed(() => {
  return models.value.filter(m => {
    if (categoryFilter.value && m.category !== categoryFilter.value) return false
    if (capabilityFilter.value && !(m.capabilities || []).includes(capabilityFilter.value)) return false
    if (search.value) {
      const q = search.value.toLowerCase()
      if (!m.name.toLowerCase().includes(q) && !m.model_id.toLowerCase().includes(q)
        && !m.description?.toLowerCase().includes(q)) return false
    }
    return true
  })
})

function isOwned(modelId: string): boolean { return myModels.value.includes(modelId) }

function handleUse(model: ModelItem): void {
  activeModel.value = model
  showAccessDialog.value = true
}

function handleApply(model: ModelItem): void {
  activeModel.value = model
  applyReason.value = ''
  showApplyDialog.value = true
}

async function submitApply(): Promise<void> {
  if (!activeModel.value) return
  applyingId.value = activeModel.value.id
  try {
    await createResourceApplication({
      resource_type: 'model',
      resource_id: activeModel.value.id,
      reason: applyReason.value,
    })
    showApplyDialog.value = false
  } finally { applyingId.value = null }
}

onMounted(async () => {
  try {
    const [modelsData, keysData, configData] = await Promise.all([
      request<ModelItem[]>('/api/v1/models/active'),
      getMyKeys(),
      request<{ litellm_base_url: string }>('/api/v1/config/public'),
    ])
    models.value = modelsData
    const mainKey = keysData.personal.find((k: AiKey) => k.key_type === 'personal_main')
    myModels.value = mainKey?.models ?? []
    mainKeyValue.value = mainKey?.key_value || mainKey?.litellm_key_id || ''
    litellmBaseUrl.value = configData.litellm_base_url || ''
  } catch { /* */ }
  finally { isLoading.value = false }
})
</script>

<template>
  <div class="mx-auto max-w-5xl px-6 py-8">
    <div class="mb-6">
      <h1 class="text-xl font-bold text-slate-900">模型广场</h1>
      <p class="mt-1 text-sm text-slate-500">浏览可用模型，申请开通后即可在客户端调用</p>
    </div>

    <!-- 搜索 + 分类筛选 -->
    <div class="mb-5 space-y-3">
      <div class="relative">
        <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input v-model="search" type="text" placeholder="搜索模型名称、ID..."
          class="h-10 w-full max-w-md rounded-lg border border-slate-200/60 bg-white pl-9 pr-3 text-sm placeholder:text-slate-400 focus:border-purple-500/50 focus:outline-none focus:ring-2 focus:ring-purple-500/20" />
      </div>
      <div class="flex flex-wrap gap-2">
        <button @click="categoryFilter = ''"
          class="rounded-full px-3 py-1 text-xs font-medium transition-colors"
          :class="!categoryFilter ? 'bg-purple-100 text-purple-700' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'">
          全部
        </button>
        <button v-for="cat in categories" :key="cat" @click="categoryFilter = cat"
          class="rounded-full px-3 py-1 text-xs font-medium transition-colors"
          :class="categoryFilter === cat ? 'bg-purple-100 text-purple-700' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'">
          {{ categoryLabel(cat) }}
        </button>
      </div>
      <div v-if="capabilities.length" class="flex flex-wrap gap-2">
        <span class="text-xs text-slate-400 leading-6">能力：</span>
        <button @click="capabilityFilter = ''"
          class="rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors"
          :class="!capabilityFilter ? 'bg-blue-100 text-blue-700' : 'bg-slate-50 text-slate-500 hover:bg-slate-100'">
          全部
        </button>
        <button v-for="cap in capabilities" :key="cap" @click="capabilityFilter = cap"
          class="rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors"
          :class="capabilityFilter === cap ? 'bg-blue-100 text-blue-700' : 'bg-slate-50 text-slate-500 hover:bg-slate-100'">
          {{ capabilityLabel(cap) }}
        </button>
      </div>
    </div>

    <!-- 卡片网格 -->
    <div v-if="isLoading" class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div v-for="i in 6" :key="i" class="h-56 animate-pulse rounded-2xl bg-white/70" />
    </div>
    <div v-else-if="!filtered.length" class="rounded-2xl border border-slate-200/60 bg-white p-12 text-center">
      <Cpu class="mx-auto h-10 w-10 text-slate-300" />
      <p class="mt-3 text-sm text-slate-400">没有匹配的模型</p>
    </div>
    <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div v-for="model in filtered" :key="model.id"
        class="group flex min-h-[220px] flex-col rounded-2xl border border-slate-200/60 bg-white p-5 transition-all hover:-translate-y-0.5 hover:shadow-lg hover:shadow-purple-500/5">
        <!-- 头部 -->
        <div class="flex items-center gap-3">
          <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-purple-50 to-blue-50">
            <ProviderIcon :src="model.icon_url" :type="model.logo_provider_type" :size="22" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <h3 class="truncate text-sm font-semibold text-slate-900">{{ model.name }}</h3>
              <CheckCircle2 v-if="isOwned(model.model_id)" class="h-3.5 w-3.5 shrink-0 text-green-500" />
            </div>
            <p class="truncate text-xs text-slate-400">{{ model.model_id }}</p>
          </div>
        </div>

        <!-- 标签 -->
        <div class="mt-3 flex flex-wrap gap-1.5">
          <span class="rounded-full bg-purple-50 px-2 py-0.5 text-xs font-medium text-purple-700">{{ categoryLabel(model.category) }}</span>
          <span v-for="cap in model.capabilities?.slice(0, 3)" :key="cap"
            class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{{ capabilityLabel(cap) }}</span>
        </div>

        <!-- 描述 -->
        <p class="mt-2.5 flex-1 text-xs leading-relaxed text-slate-500">{{ model.description || '暂无描述' }}</p>

        <!-- 底部操作 -->
        <div class="mt-4 border-t border-slate-100 pt-3">
          <button v-if="isOwned(model.model_id) || !model.requires_approval" @click="handleUse(model)"
            class="w-full rounded-lg bg-gradient-to-r from-purple-600 to-blue-600 py-2 text-xs font-medium text-white opacity-0 shadow-sm transition-opacity group-hover:opacity-100">
            查看接入信息
          </button>
          <button v-else @click="handleApply(model)"
            class="w-full rounded-lg border border-purple-200 bg-purple-50 py-2 text-xs font-medium text-purple-700 opacity-0 transition-opacity group-hover:opacity-100">
            申请使用
          </button>
        </div>
      </div>
    </div>

    <!-- 接入信息弹窗 -->
    <ModelAccessDialog :visible="showAccessDialog" :model="activeModel" :main-key-value="mainKeyValue"
      :litellm-base-url="litellmBaseUrl" @close="showAccessDialog = false" />

    <!-- 申请弹窗 -->
    <div v-if="showApplyDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-2xl">
        <div class="flex items-center justify-between">
          <h3 class="text-base font-semibold text-slate-900">申请使用：{{ activeModel?.name }}</h3>
          <button @click="showApplyDialog = false" class="rounded-lg p-1 hover:bg-slate-100"><X class="h-4 w-4 text-slate-400" /></button>
        </div>
        <textarea v-model="applyReason" rows="3" placeholder="申请理由（可选）"
          class="mt-4 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm placeholder:text-slate-400 focus:border-purple-500/50 focus:outline-none focus:ring-2 focus:ring-purple-500/20" />
        <div class="mt-4 flex justify-end gap-2">
          <button @click="showApplyDialog = false" class="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">取消</button>
          <button @click="submitApply" :disabled="applyingId !== null"
            class="rounded-lg bg-gradient-to-r from-purple-600 to-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm disabled:opacity-50">
            {{ applyingId ? '提交中...' : '提交申请' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
