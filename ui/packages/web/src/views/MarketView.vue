<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getMyKeys, search, request, createResourceApplication, StarRating, LabelBadge } from '@aihelms/shared'
import type { AiKey, Skill, McpServer, SearchResultItem, SkillLabelGrant } from '@aihelms/shared'
import { Server, Sparkles, CheckCircle2, Search, X, ExternalLink, Flame } from 'lucide-vue-next'
import * as lucideIcons from 'lucide-vue-next'
import SkillInstallDialog from '../components/SkillInstallDialog.vue'
import RatingWidget from '../components/RatingWidget.vue'

type MarketItem = (Skill & { _type: 'skill' }) | (McpServer & { _type: 'mcp' })

const items = ref<MarketItem[]>([])
const mySkills = ref<number[]>([])
const myMcps = ref<number[]>([])
const isLoading = ref(true)
const searchQuery = ref('')
const searchResults = ref<SearchResultItem[]>([])
const isSearching = ref(false)
const typeFilter = ref<'all' | 'skill' | 'mcp' | 'tool'>('all')
const sortMode = ref<'latest' | 'rating' | 'usage'>('rating')
const { t } = useI18n()
const categoryFilter = ref('')
const showApplyDialog = ref(false)
const showMcpAccessDialog = ref(false)
const applyTarget = ref<MarketItem | null>(null)
const mcpTarget = ref<McpServer | null>(null)
const applyReason = ref('')
const applyingId = ref<number | null>(null)
let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null

const categories = computed(() => {
  const base = items.value.filter(i => typeFilter.value === 'all' || itemToType(i) === typeFilter.value)
  const set = new Set(base.map(i => i.category).filter(Boolean))
  return Array.from(set).sort()
})

async function copyToClipboard(text: string): Promise<void> {
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
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
  } catch { /* ignore */ }
}

// Backend search results — displayed when user is actively searching
const backendResults = computed<MarketItem[]>(() => {
  if (!searchQuery.value || searchResults.value.length === 0) return []
  // Map backend SearchResultItem back to MarketItem-like structure for template
  return searchResults.value.map(r => {
    const meta = r.metadata as Record<string, unknown> | undefined
    const type = r.entity_type === 'skill' ? 'skill' : 'mcp'
    return {
      _type: type,
      name: r.name,
      description: r.description,
      entity_type: r.entity_type,
      entity_id: r.entity_id,
      id: r.entity_id,
      category: (meta as Record<string, unknown>)?.category as string | undefined,
      tags: (meta as Record<string, unknown>)?.tags as string[] || [],
      author: (meta as Record<string, unknown>)?.author as string | undefined,
      install_count: (meta as Record<string, unknown>)?.install_count as number | 0,
      call_count: (meta as Record<string, unknown>)?.call_count as number | 0,
      requires_approval: false,
    } as unknown as MarketItem
  })
})

// Q5: rating_count >= 3 threshold prevents low-sample score from dominating
function qualityScore(item: MarketItem): number {
  const cnt = item.rating_count ?? 0
  const avg = item.avg_score ?? 0
  return cnt >= 3 ? avg : 0
}

function sortItems(list: MarketItem[]): MarketItem[] {
  const copy = [...list]
  if (sortMode.value === 'rating') {
    copy.sort((a, b) => qualityScore(b) - qualityScore(a) || getUsageCount(b) - getUsageCount(a))
  } else if (sortMode.value === 'usage') {
    copy.sort((a, b) => getUsageCount(b) - getUsageCount(a))
  } else {
    copy.sort((a, b) => b.id - a.id)
  }
  return copy
}

// Display items: when searching, show backend results; otherwise use client-side filtered
const displayItems = computed<MarketItem[]>(() => {
  if (searchQuery.value && backendResults.value.length > 0) return sortItems(backendResults.value)
  const filtered = items.value.filter(item => {
    if (typeFilter.value !== 'all' && itemToType(item) !== typeFilter.value) return false
    if (categoryFilter.value && item.category !== categoryFilter.value) return false
    return true
  })
  return sortItems(filtered)
})

function itemToType(item: MarketItem): 'skill' | 'mcp' {
  return item._type
}

function isOwned(item: MarketItem): boolean {
  return item._type === 'skill' ? mySkills.value.includes(item.id) : myMcps.value.includes(item.id)
}

// S4 · 治理 Label（仅 skill 携带）
function getLabels(item: MarketItem): SkillLabelGrant[] {
  return item._type === 'skill' ? item.labels ?? [] : []
}

// recommended 置顶区（显式标注位，不进质量分）
const recommendedItems = computed<MarketItem[]>(() =>
  displayItems.value.filter(i => i._type === 'skill' && getLabels(i).some(l => l.name === 'recommended')),
)

function getTags(item: MarketItem): string[] {
  return item.tags?.slice(0, 3) ?? []
}

function getIconUrl(item: MarketItem): string {
  if (item._type === 'mcp') return (item as unknown as McpServer).icon_url || ''
  return ''
}

function getSkillIcon(item: MarketItem): string {
  if (item._type === 'skill') return (item as unknown as Skill).icon || ''
  return ''
}

function getLucideIcon(name: string) {
  return (lucideIcons as Record<string, unknown>)[name] || null
}

function getAuthor(item: MarketItem): string {
  return item.author ?? ''
}

function getUsageCount(item: MarketItem): number {
  if (item._type === 'skill') return (item as Skill).install_count ?? 0
  return (item as McpServer).call_count ?? 0
}

function formatUsageCount(count: number): string {
  if (count >= 1_000_000) return `${Math.floor(count / 100_000) / 10}M`
  if (count >= 10_000) return `${Math.floor(count / 1000)}K`
  if (count >= 1000) return `${Math.floor(count / 100) / 10}K`
  return String(count)
}

async function performSearch(keyword: string): Promise<void> {
  if (!keyword.trim()) {
    searchResults.value = []
    return
  }
  isSearching.value = true
  try {
    // Map frontend typeFilter to backend entity_types
    const etypes: string[] = []
    if (typeFilter.value === 'all' || typeFilter.value === 'skill') etypes.push('skill')
    if (typeFilter.value === 'all' || typeFilter.value === 'mcp') {
      etypes.push('mcp_server')
    }
    const res = await search(
      { q: keyword.trim(), entity_types: etypes, category: categoryFilter.value || undefined },
      { page: 1, page_size: 50 },
    )
    searchResults.value = res?.items ?? []
  } catch {
    /* ignore search errors, fall back to empty */
    searchResults.value = []
  } finally {
    isSearching.value = false
  }
}

function handleSearchInput(value: string): void {
  searchQuery.value = value
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  if (!value.trim()) {
    searchResults.value = []
    return
  }
  searchDebounceTimer = setTimeout(() => {
    performSearch(value)
  }, 350)
}

onUnmounted(() => {
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
})

async function handleCopyPrompt(item: MarketItem) {
  if (item._type !== 'skill') return
  skillTarget.value = item as unknown as Skill
  skillInstallInfo.value = null
  showSkillInstallDialog.value = true
  loadSkillInstall(item.id)
}

async function loadSkillInstall(skillId: number) {
  skillInstallLoading.value = true
  try {
    skillInstallInfo.value = await request<SkillInstallInfo>(`/api/v1/skills/${skillId}/install-info`)
  } catch { /* */ }
  finally { skillInstallLoading.value = false }
}

async function copySkillPrompt() {
  if (!skillInstallInfo.value) return
  await copyToClipboard(skillInstallInfo.value.agent_prompt)
  skillPromptCopied.value = true
  setTimeout(() => { skillPromptCopied.value = false }, 2000)
}

interface SkillInstallInfo {
  name: string
  description: string
  agent_prompt: string
  download_url: string
  usage_instructions: string
  author?: string
}

const showSkillInstallDialog = ref(false)
const skillTarget = ref<Skill | null>(null)
const skillInstallInfo = ref<SkillInstallInfo | null>(null)
const skillInstallLoading = ref(false)
const skillPromptCopied = ref(false)

function handleViewAccess(item: MarketItem) {
  if (item._type !== 'mcp') return
  mcpTarget.value = item as unknown as McpServer
  mcpConnectConfig.value = null
  showMcpAccessDialog.value = true
  loadMcpConfig(item.id)
}

interface McpConnectConfig {
  name: string
  description: string
  author?: string
  agent_prompt: string
  config: Record<string, unknown>
  instructions: string
  tools: Array<{ name: string; description: string }>
}

const mcpConnectConfig = ref<McpConnectConfig | null>(null)
const mcpConfigLoading = ref(false)
const mcpConfigCopied = ref(false)

async function loadMcpConfig(serverId: number) {
  mcpConfigLoading.value = true
  try {
    const res = await request<McpConnectConfig>(`/api/v1/mcp/servers/${serverId}/connect-config`)
    mcpConnectConfig.value = res
  } catch { /* */ }
  finally { mcpConfigLoading.value = false }
}

function getSkillDialogAuthor(): string {
  return skillInstallInfo.value?.author ?? skillTarget.value?.author ?? ''
}

function getMcpDialogAuthor(): string {
  return mcpConnectConfig.value?.author ?? mcpTarget.value?.author ?? ''
}

function getSkillDialogUsageCount(): number {
  return skillTarget.value?.install_count ?? 0
}

function getMcpDialogUsageCount(): number {
  return mcpTarget.value?.call_count ?? 0
}

async function copyMcpConfig() {
  if (!mcpConnectConfig.value) return
  const text = mcpConnectConfig.value.agent_prompt + JSON.stringify(mcpConnectConfig.value.config, null, 2)
  await copyToClipboard(text)
  mcpConfigCopied.value = true
  setTimeout(() => { mcpConfigCopied.value = false }, 2000)
}

function handleApply(item: MarketItem) {
  applyTarget.value = item
  applyReason.value = ''
  showApplyDialog.value = true
}

async function submitApply() {
  if (!applyTarget.value) return
  applyingId.value = applyTarget.value.id
  try {
    await createResourceApplication({
      resource_type: applyTarget.value._type,
      resource_id: applyTarget.value.id,
      reason: applyReason.value.trim(),
    })
    showApplyDialog.value = false
  } finally {
    applyingId.value = null
  }
}

async function loadData() {
  isLoading.value = true
  try {
    const [skillRes, mcpRes, keysRes] = await Promise.all([
      request<{ items: Skill[] }>('/api/v1/skills/published', { params: { page_size: 100 } }),
      request<{ items: McpServer[] }>('/api/v1/mcp/servers/published', { params: { page_size: 100 } }),
      getMyKeys(),
    ])
    const skillItems: MarketItem[] = (skillRes?.items ?? []).map(s => ({ ...s, _type: 'skill' as const }))
    const mcpItems: MarketItem[] = (mcpRes?.items ?? []).map(m => ({ ...m, _type: 'mcp' as const }))
    items.value = [...skillItems, ...mcpItems]

    const mainKey = keysRes.personal?.find((k: AiKey) => k.key_type === 'personal_main')
    mySkills.value = mainKey?.skills ?? []
    myMcps.value = mainKey?.mcps ?? []
  } finally {
    isLoading.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div class="mx-auto max-w-6xl px-6 py-8 space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold text-slate-800">AI 市场</h1>
    </div>

    <!-- Filters -->
    <div class="space-y-4">
      <!-- Type filter + Search -->
      <div class="flex items-center gap-4">
        <div class="flex items-center gap-1 rounded-xl bg-white p-1 border border-slate-200/60">
          <button
            v-for="opt in [{ key: 'all', label: '全部' }, { key: 'skill', label: 'Skill' }, { key: 'mcp', label: 'MCP' }]"
            :key="opt.key"
            class="rounded-lg px-4 py-1.5 text-sm font-medium transition-all"
            :class="typeFilter === opt.key
              ? 'bg-gradient-to-r from-purple-500 to-blue-500 text-white shadow-sm'
              : 'text-slate-600 hover:text-slate-900'"
            @click="typeFilter = opt.key as 'all' | 'skill' | 'mcp'"
          >
            {{ opt.label }}
          </button>
        </div>
        <div class="relative flex-1 max-w-xs">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            v-model="searchQuery"
            @input="handleSearchInput(($event.target as HTMLInputElement).value)"
            type="text"
            placeholder="搜索 Skill / MCP ..."
            class="w-full rounded-xl border border-slate-200/60 bg-white py-2 pl-9 pr-4 text-sm placeholder:text-slate-400 focus:border-purple-300 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
          />
        </div>
        <div class="flex items-center gap-1 rounded-xl bg-white p-1 border border-slate-200/60">
          <button
            v-for="opt in [{ key: 'latest', label: t('market.sort.latest') }, { key: 'rating', label: t('market.sort.rating') }, { key: 'usage', label: t('market.sort.usage') }]"
            :key="opt.key"
            class="rounded-lg px-3 py-1.5 text-xs font-medium transition-all"
            :class="sortMode === opt.key
              ? 'bg-gradient-to-r from-purple-500 to-blue-500 text-white shadow-sm'
              : 'text-slate-600 hover:text-slate-900'"
            @click="sortMode = opt.key as 'latest' | 'rating' | 'usage'"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>
      <!-- Category tags -->
      <div v-if="categories.length" class="flex flex-wrap items-center gap-2">
        <button
          class="rounded-lg px-3 py-1 text-xs font-medium transition-all"
          :class="!categoryFilter
            ? 'bg-purple-100 text-purple-700'
            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'"
          @click="categoryFilter = ''"
        >
          全部分类
        </button>
        <button
          v-for="cat in categories"
          :key="cat"
          class="rounded-lg px-3 py-1 text-xs font-medium transition-all"
          :class="categoryFilter === cat
            ? 'bg-purple-100 text-purple-700'
            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'"
          @click="categoryFilter = cat"
        >
          {{ cat }}
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="isLoading || isSearching" class="flex items-center justify-center py-20">
      <div class="h-8 w-8 animate-spin rounded-full border-2 border-purple-500 border-t-transparent" />
    </div>

    <!-- Empty -->
    <div v-else-if="!displayItems.length" class="py-20 text-center text-slate-400">
      暂无可用资源
    </div>

    <!-- Card Grid -->
    <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      <!-- S4 · recommended 置顶区（显式标注位，不进质量分） -->
      <div v-if="recommendedItems.length" class="col-span-full mb-2 rounded-2xl border border-green-200/60 bg-gradient-to-r from-green-50/60 to-transparent p-4">
        <h3 class="mb-3 flex items-center gap-1.5 text-sm font-semibold text-green-700">
          <Flame class="h-4 w-4 text-green-500" /> {{ t('label.recommended.title') }}
        </h3>
        <div class="flex gap-3 overflow-x-auto pb-1">
          <div
            v-for="item in recommendedItems"
            :key="`rec-${item._type}-${item.id}`"
            class="flex min-w-[200px] max-w-[220px] flex-col rounded-xl border border-slate-200/60 bg-white p-3"
          >
            <div class="mb-1 flex items-center gap-1.5">
              <component
                :is="getLucideIcon(getIconUrl(item) || getSkillIcon(item))"
                v-if="getLucideIcon(getIconUrl(item) || getSkillIcon(item))"
                class="h-4 w-4 text-purple-600"
              />
              <Sparkles v-else class="h-4 w-4 text-purple-600" />
              <LabelBadge
                v-for="l in getLabels(item)"
                :key="l.name"
                :name="l.name"
                :display_name_key="l.display_name_key"
                :color="l.color"
                size="sm"
              />
            </div>
            <h4 class="mb-1 text-sm font-semibold text-slate-800 line-clamp-1">{{ item.name }}</h4>
            <p class="mb-2 flex-1 text-xs text-slate-500 line-clamp-2">{{ item.description }}</p>
            <button
              v-if="(isOwned(item) || !item.requires_approval) && item._type === 'skill'"
              class="rounded-lg bg-gradient-to-r from-green-500 to-emerald-500 px-3 py-1 text-xs font-medium text-white"
              @click="handleCopyPrompt(item)"
            >
              安装 Skill
            </button>
            <button
              v-else
              class="rounded-lg bg-gradient-to-r from-green-500 to-emerald-500 px-3 py-1 text-xs font-medium text-white"
              @click="handleApply(item)"
            >
              申请使用
            </button>
          </div>
        </div>
      </div>
      <div
        v-for="item in displayItems"
        :key="`${item._type}-${item.id}`"
        class="group relative flex min-h-[200px] flex-col rounded-2xl border border-slate-200/60 bg-white p-5 transition-all duration-300 hover:-translate-y-1 hover:shadow-lg hover:shadow-purple-500/5"
      >
        <!-- Icon + Type badge -->
        <div class="mb-3 flex items-start justify-between">
          <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-100 to-blue-100">
            <component
              :is="getLucideIcon(getIconUrl(item) || getSkillIcon(item))"
              v-if="getLucideIcon(getIconUrl(item) || getSkillIcon(item))"
              class="h-5 w-5 text-purple-600"
            />
            <Server v-else-if="item._type === 'mcp'" class="h-5 w-5 text-blue-600" />
            <Sparkles v-else class="h-5 w-5 text-purple-600" />
          </div>
          <div class="flex items-center gap-1.5">
            <CheckCircle2 v-if="isOwned(item)" class="h-4 w-4 text-green-500" />
            <LabelBadge
              v-for="l in getLabels(item)"
              :key="l.name"
              :name="l.name"
              :display_name_key="l.display_name_key"
              :color="l.color"
              size="sm"
            />
            <span
              class="rounded-md px-2 py-0.5 text-xs font-medium"
              :class="item._type === 'skill' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'"
            >
              {{ item._type === 'skill' ? 'Skill' : 'MCP' }}
            </span>
          </div>
        </div>

        <!-- Name + Category -->
          <div class="mb-1 flex items-start justify-between gap-3">
            <h3 class="min-w-0 flex-1 text-sm font-semibold text-slate-800 line-clamp-1">{{ item.name }}</h3>
            <span v-if="getAuthor(item)" class="max-w-[6em] shrink-0 truncate text-xs text-slate-400">{{ getAuthor(item) }}</span>
          </div>
        <p v-if="item.category" class="mb-2 text-xs text-slate-400">{{ item.category }}</p>

        <!-- Tags -->
          <div class="mb-2 flex items-start justify-between gap-2">
            <div v-if="getTags(item).length" class="flex min-w-0 flex-wrap gap-1">
              <span
                v-for="tag in getTags(item)"
                :key="tag"
                class="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500"
              >
                {{ tag }}
              </span>
            </div>
            <div v-else class="min-w-0" />
            <span class="flex shrink-0 items-center gap-1 pt-0.5 text-xs text-slate-400 tabular-nums">
              <Flame class="h-3.5 w-3.5 text-orange-500" />
              {{ formatUsageCount(getUsageCount(item)) }}
            </span>
          </div>
        <!-- Rating -->
        <div v-if="(item.rating_count ?? 0) > 0" class="mb-2">
          <StarRating :readonly-value="item.avg_score ?? 0" :count="item.rating_count ?? 0" readonly size="sm" />
        </div>
        <!-- Description -->
        <p class="flex-1 text-xs leading-relaxed text-slate-500 line-clamp-3">{{ item.description }}</p>
        <!-- Hover actions -->
        <div class="absolute inset-x-0 bottom-0 flex items-center justify-center rounded-b-2xl bg-gradient-to-t from-white/90 to-transparent px-5 pb-4 pt-8 opacity-0 transition-opacity duration-300 group-hover:opacity-100">
          <button
            v-if="(isOwned(item) || !item.requires_approval) && item._type === 'skill'"
            class="rounded-lg bg-gradient-to-r from-purple-500 to-blue-500 px-4 py-1.5 text-xs font-medium text-white shadow-sm transition-transform hover:scale-105"
            @click="handleCopyPrompt(item)"
          >
            安装 Skill
          </button>
          <button
            v-else-if="(isOwned(item) || !item.requires_approval) && item._type === 'mcp'"
            class="flex items-center gap-1 rounded-lg bg-gradient-to-r from-blue-500 to-cyan-500 px-4 py-1.5 text-xs font-medium text-white shadow-sm transition-transform hover:scale-105"
            @click="handleViewAccess(item)"
          >
            <ExternalLink class="h-3 w-3" />
            查看接入信息
          </button>
          <button
            v-else
            class="rounded-lg bg-gradient-to-r from-purple-500 to-blue-500 px-4 py-1.5 text-xs font-medium text-white shadow-sm transition-transform hover:scale-105"
            @click="handleApply(item)"
          >
            申请使用
          </button>
        </div>
      </div>
    </div>

    <!-- Apply Dialog -->
    <Teleport to="body">
      <div v-if="showApplyDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30" @click.self="showApplyDialog = false">
        <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
          <div class="mb-4 flex items-center justify-between">
            <h3 class="text-lg font-semibold text-slate-800">申请使用</h3>
            <button class="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" @click="showApplyDialog = false">
              <X class="h-5 w-5" />
            </button>
          </div>
          <p class="mb-3 text-sm text-slate-500">
            申请使用「{{ applyTarget?.name }}」，请填写申请理由：
          </p>
          <textarea
            v-model="applyReason"
            rows="4"
            placeholder="请描述使用场景和理由..."
            class="w-full rounded-xl border border-slate-200/60 bg-white px-4 py-3 text-sm placeholder:text-slate-400 focus:border-purple-300 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
          />
          <div class="mt-4 flex justify-end gap-3">
            <button
              class="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100"
              @click="showApplyDialog = false"
            >
              取消
            </button>
            <button
              class="rounded-lg bg-gradient-to-r from-purple-500 to-blue-500 px-4 py-2 text-sm font-medium text-white shadow-sm disabled:opacity-50"
              :disabled="!applyReason.trim() || applyingId !== null"
              @click="submitApply"
            >
              {{ applyingId !== null ? '提交中...' : '提交申请' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- MCP Access Dialog -->
    <Teleport to="body">
      <div v-if="showMcpAccessDialog && mcpTarget" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30" @click.self="showMcpAccessDialog = false">
        <div class="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border border-slate-200/60 bg-white shadow-xl">
            <div class="flex items-center justify-between gap-4 border-b border-slate-100 px-6 py-4">
              <div class="flex min-w-0 items-center gap-2">
                <h3 class="truncate text-lg font-semibold text-slate-800">{{ mcpTarget.name }}</h3>
                <span v-if="getMcpDialogAuthor()" class="max-w-[6em] shrink-0 truncate text-xs text-slate-400">{{ getMcpDialogAuthor() }}</span>
                <span class="flex shrink-0 items-center gap-1 text-xs text-slate-400 tabular-nums">
                  <Flame class="h-3.5 w-3.5 text-orange-500" />
                  {{ formatUsageCount(getMcpDialogUsageCount()) }}
                </span>
              </div>
            <button class="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" @click="showMcpAccessDialog = false">
              <X class="h-5 w-5" />
            </button>
          </div>

          <div class="flex-1 overflow-y-auto px-6 py-5">
            <!-- 加载中 -->
            <div v-if="mcpConfigLoading" class="flex items-center justify-center py-10">
              <div class="h-6 w-6 animate-spin rounded-full border-2 border-purple-500 border-t-transparent" />
            </div>

            <template v-else-if="mcpConnectConfig">
              <!-- 介绍 -->
              <p v-if="mcpConnectConfig.description" class="mb-4 whitespace-pre-wrap text-sm leading-relaxed text-slate-600">{{ mcpConnectConfig.description }}</p>

              <!-- 安装配置 -->
              <div class="mb-4">
                <label class="mb-2 block text-xs font-semibold text-slate-700">安装配置</label>
                <div class="rounded-lg bg-slate-900 p-4">
                  <pre class="whitespace-pre-wrap text-xs leading-relaxed text-green-300">{{ mcpConnectConfig.agent_prompt }}{{ JSON.stringify(mcpConnectConfig.config, null, 2) }}</pre>
                </div>
                <button @click="copyMcpConfig"
                  class="mt-2 rounded-lg bg-gradient-to-r from-purple-500 to-blue-500 px-4 py-1.5 text-xs font-medium text-white shadow-sm">
                  {{ mcpConfigCopied ? '已复制' : '复制安装配置' }}
                </button>
              </div>

              <!-- 包含工具（支持多个） -->
              <div v-if="mcpConnectConfig.tools.length" class="mb-4">
                <label class="mb-2 block text-xs font-semibold text-slate-700">包含工具（{{ mcpConnectConfig.tools.length }}）</label>
                <div class="space-y-2 rounded-lg bg-slate-50 p-3">
                  <div v-for="tool in mcpConnectConfig.tools" :key="tool.name" class="flex items-baseline gap-2">
                    <span class="inline-block h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full bg-purple-400" />
                    <div class="min-w-0 flex-1">
                      <span class="text-xs font-medium text-slate-800">{{ tool.name }}</span>
                      <span v-if="tool.description" class="ml-1.5 text-xs text-slate-500">{{ tool.description }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 使用说明 -->
              <div v-if="mcpConnectConfig.instructions">
                <label class="mb-2 block text-xs font-semibold text-slate-700">使用说明</label>
                <div class="rounded-lg bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-700 whitespace-pre-wrap">{{ mcpConnectConfig.instructions }}</div>
              </div>

              <!-- Rating -->
              <div class="mt-4 border-t border-slate-100 pt-4">
                <h4 class="mb-3 text-xs font-semibold text-slate-700">{{ t('market.rating.title') }}</h4>
                <RatingWidget entity-type="mcp_server" :entity-id="mcpTarget.id" />
              </div>
            </template>
          </div>

          <div class="flex justify-end border-t border-slate-100 px-6 py-3">
            <button class="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100" @click="showMcpAccessDialog = false">关闭</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Skill Install Dialog -->
    <SkillInstallDialog
      v-if="showSkillInstallDialog && skillTarget"
      :visible="showSkillInstallDialog"
      :skill="skillTarget"
      @close="showSkillInstallDialog = false"
    />
  </div>
</template>

