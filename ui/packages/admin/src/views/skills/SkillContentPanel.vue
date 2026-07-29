<script setup lang="ts">
import { ref, watch, computed, onMounted } from 'vue'
import {
  getSkillSummary,
  getSkillFull,
  getSkillIntegrity,
  checkSkillVersionDrift,
  usePermission,
  type SkillSummaryView,
  type SkillFullView,
  type SkillIntegrityView,
  type ManifestFile,
} from '@aihelms/shared'
import MarkdownRenderer from '@aihelms/shared/src/components/MarkdownRenderer.vue'
import { ShieldCheck, CheckCircle2, AlertTriangle, XCircle, FileText, X } from 'lucide-vue-next'
import { toast } from '@aihelms/shared'

interface Props {
  skillId: number
}

const props = defineProps<Props>()
const { hasPermission } = usePermission()

type DisclosureLayer = 'overview' | 'summary'
const activeLayer = ref<DisclosureLayer>('overview')
const summaryData = ref<SkillSummaryView | null>(null)
const fullData = ref<SkillFullView | null>(null)
const integrityData = ref<SkillIntegrityView | null>(null)
const summaryLoading = ref(false)
const fullLoading = ref(false)
const checkingDrift = ref(false)
const showFullDrawer = ref(false)
const showIntegrityDrawer = ref(false)

async function loadSummary(): Promise<void> {
  if (summaryData.value) return
  summaryLoading.value = true
  try {
    summaryData.value = await getSkillSummary(props.skillId)
  } catch {
    toast.error('加载摘要失败')
  } finally {
    summaryLoading.value = false
  }
}

async function loadFull(): Promise<void> {
  if (fullData.value) return
  fullLoading.value = true
  try {
    fullData.value = await getSkillFull(props.skillId)
  } catch {
    toast.error('加载完整内容失败')
  } finally {
    fullLoading.value = false
  }
}

async function loadIntegrity(force = false): Promise<void> {
  if (!force && integrityData.value) return
  try {
    integrityData.value = await getSkillIntegrity(props.skillId)
  } catch {
    toast.error('加载完整性信息失败')
  }
}

async function handleCheckDrift(): Promise<void> {
  if (!integrityData.value?.version_id) return
  checkingDrift.value = true
  try {
    await checkSkillVersionDrift(props.skillId, integrityData.value.version_id)
    integrityData.value = null
    await loadIntegrity(true)
    toast.success('漂移检测完成')
  } catch (e) {
    toast.error((e as { message?: string }).message || '漂移检测失败')
  } finally {
    checkingDrift.value = false
  }
}

async function switchLayer(layer: DisclosureLayer): Promise<void> {
  activeLayer.value = layer
  if (layer === 'overview' || layer === 'summary') await loadSummary()
}

function openFullDrawer(): void {
  showFullDrawer.value = true
  loadFull()
}

function openIntegrityDrawer(): void {
  showIntegrityDrawer.value = true
  loadIntegrity()
}

onMounted(() => {
  if (props.skillId) loadSummary()
})

function formatFrontmatterValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value ?? '')
}

const CATEGORY_LABELS: Record<string, string> = {
  root: '根文件',
  references: '引用文档 (references)',
  scripts: '脚本 (scripts)',
  assets: '资源 (assets)',
  other: '其他',
}
const CATEGORY_ORDER = ['root', 'references', 'scripts', 'assets', 'other']

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

interface ManifestEntry {
  path: string
  sha: string
  size: number
  content_type?: string
  category: string
}

const manifestGroups = computed<{ category: string; files: ManifestEntry[] }[]>(() => {
  const hashes = integrityData.value?.file_hashes ?? {}
  const entries: ManifestEntry[] = Object.entries(hashes).map(([path, file]) => {
    const f = file as ManifestFile
    return {
      path,
      sha: f.sha256 ?? '',
      size: f.size ?? 0,
      content_type: f.content_type,
      category: f.category ?? 'other',
    }
  })
  return CATEGORY_ORDER.filter((cat) => entries.some((e) => e.category === cat)).map(
    (category) => ({
      category,
      files: entries
        .filter((e) => e.category === category)
        .sort((a, b) => a.path.localeCompare(b.path)),
    }),
  )
})

const protocolErrors = computed(
  () => (integrityData.value?.protocol_errors ?? []).filter((i) => i.severity === 'error'),
)
const protocolWarnings = computed(
  () => (integrityData.value?.protocol_errors ?? []).filter((i) => i.severity === 'warning'),
)

const tabs: { key: DisclosureLayer; label: string }[] = [
  { key: 'overview', label: '概览' },
  { key: 'summary', label: '摘要' },
]

watch(
  () => props.skillId,
  () => {
    activeLayer.value = 'overview'
    summaryData.value = null
    fullData.value = null
    integrityData.value = null
    showFullDrawer.value = false
    showIntegrityDrawer.value = false
    loadSummary()
  },
)
</script>

<template>
  <div class="mb-4 rounded-xl border border-slate-200/60 p-3">
    <div class="mb-2 flex items-center justify-between">
      <h4 class="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
        <FileText class="h-4 w-4 text-purple-500" /> 内容
      </h4>
      <div class="flex items-center gap-2">
        <button
          class="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
          @click="openFullDrawer"
        >
          <FileText class="h-3.5 w-3.5" /> 完整指令
        </button>
        <button
          v-if="hasPermission('skill:read')"
          class="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
          @click="openIntegrityDrawer"
        >
          <ShieldCheck class="h-3.5 w-3.5" /> 内容完整性
        </button>
      </div>
    </div>

    <!-- Tab header -->
    <div class="mb-2 flex gap-1 border-b border-slate-200/60">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="-mb-px border-b-2 px-3 py-1.5 text-sm font-medium transition-colors"
        :class="
          activeLayer === tab.key
            ? 'border-purple-500 text-purple-600'
            : 'border-transparent text-slate-500 hover:text-slate-700'
        "
        @click="switchLayer(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Tab content -->
    <div>
      <!-- Overview: frontmatter key-value table -->
      <div v-if="activeLayer === 'overview'">
        <div v-if="summaryData?.frontmatter && Object.keys(summaryData.frontmatter).length > 0" class="space-y-2">
          <div
            v-for="(value, key) in summaryData.frontmatter"
            :key="key"
            class="flex items-start gap-3 rounded-lg bg-gray-50 px-3 py-2"
          >
            <span class="min-w-24 shrink-0 text-sm font-medium text-gray-500">{{ key }}</span>
            <span class="text-sm text-gray-800 break-all">{{ formatFrontmatterValue(value) }}</span>
          </div>
        </div>
        <div v-else class="py-8 text-center text-sm text-gray-400">
          该 Skill 未包含 SKILL.md 文件，无 frontmatter 信息
        </div>
      </div>

      <!-- Summary: rendered markdown -->
      <div v-if="activeLayer === 'summary'">
        <div v-if="summaryLoading" class="py-8 text-center text-sm text-gray-400">加载中...</div>
        <div v-else-if="summaryData?.summary_text">
          <MarkdownRenderer :content="summaryData.summary_text" />
        </div>
        <div v-else class="py-8 text-center text-sm text-gray-400">
          该 Skill 无摘要内容
        </div>
      </div>
    </div>

    <!-- 完整指令 抽屉 -->
    <Teleport to="body">
      <div v-if="showFullDrawer" class="fixed inset-0 z-50">
        <div class="absolute inset-0 bg-black/30" @click="showFullDrawer = false" />
        <aside class="absolute right-0 top-0 flex h-full w-full max-w-3xl flex-col bg-white shadow-2xl">
          <div class="flex shrink-0 items-center justify-between border-b border-slate-200 px-5 py-3">
            <span class="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
              <FileText class="h-4 w-4 text-purple-500" /> 完整指令
            </span>
            <button
              class="flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-100"
              aria-label="关闭"
              @click="showFullDrawer = false"
            >
              <X class="h-4 w-4" />
            </button>
          </div>
          <div class="flex-1 overflow-y-auto px-5 py-4">
            <div v-if="fullLoading" class="py-8 text-center text-sm text-gray-400">加载中...</div>
            <div v-else-if="fullData?.full_content">
              <MarkdownRenderer :content="fullData.full_content" />
            </div>
            <div v-else class="py-8 text-center text-sm text-gray-400">
              该 Skill 无完整内容
            </div>
          </div>
        </aside>
      </div>
    </Teleport>

    <!-- 内容完整性 抽屉 -->
    <Teleport to="body">
      <div v-if="showIntegrityDrawer" class="fixed inset-0 z-50">
        <div class="absolute inset-0 bg-black/30" @click="showIntegrityDrawer = false" />
        <aside class="absolute right-0 top-0 flex h-full w-full max-w-3xl flex-col bg-white shadow-2xl">
          <div class="flex shrink-0 items-center justify-between border-b border-slate-200 px-5 py-3">
            <span class="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
              <ShieldCheck class="h-4 w-4 text-purple-500" /> 内容完整性
            </span>
            <button
              class="flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-100"
              aria-label="关闭"
              @click="showIntegrityDrawer = false"
            >
              <X class="h-4 w-4" />
            </button>
          </div>
          <div class="flex-1 overflow-y-auto px-5 py-4">
            <div v-if="!integrityData" class="py-8 text-center text-sm text-gray-400">
              加载中...
            </div>
            <div v-else class="space-y-3 text-sm">
              <!-- 协议合规状态 -->
              <div class="flex items-center gap-2">
                <span v-if="integrityData.protocol_valid" class="flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                  <CheckCircle2 class="h-3.5 w-3.5" /> 协议合规
                </span>
                <span v-else class="flex items-center gap-1 rounded-md bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
                  <XCircle class="h-3.5 w-3.5" /> 协议不合规
                </span>
                <span v-if="protocolWarnings.length" class="flex items-center gap-1 text-xs text-amber-600">
                  <AlertTriangle class="h-3.5 w-3.5" /> {{ protocolWarnings.length }} 条告警
                </span>
              </div>
              <ul v-if="protocolErrors.length" class="space-y-1">
                <li v-for="(issue, idx) in protocolErrors" :key="`err-${idx}`" class="rounded bg-red-50 px-2 py-1 text-xs text-red-700">
                  {{ issue.message }}
                </li>
              </ul>
              <ul v-if="protocolWarnings.length" class="space-y-1">
                <li v-for="(issue, idx) in protocolWarnings" :key="`warn-${idx}`" class="rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">
                  {{ issue.message }}
                </li>
              </ul>
              <div class="flex gap-3">
                <span class="min-w-28 shrink-0 text-gray-500">composite_hash</span>
                <code class="break-all text-xs font-mono text-gray-700">
                  {{ integrityData.composite_hash || '—' }}
                </code>
              </div>
              <div class="flex gap-3">
                <span class="min-w-28 shrink-0 text-gray-500">source_type</span>
                <span class="text-gray-700">{{ integrityData.source_type }}</span>
              </div>
              <div v-if="integrityData.source_type === 'url' && integrityData.version_id" class="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                <div class="flex items-center justify-between gap-2">
                  <span class="text-xs text-gray-500">
                    上次检测：{{ integrityData.last_drift_check_at ? new Date(integrityData.last_drift_check_at).toLocaleString() : '未检测' }}
                  </span>
                  <button
                    class="rounded px-2 py-0.5 text-xs font-medium text-gray-600 hover:bg-gray-200 disabled:opacity-50"
                    :disabled="checkingDrift"
                    @click="handleCheckDrift"
                  >
                    {{ checkingDrift ? '检测中…' : '立即检测' }}
                  </button>
                </div>
                <div v-if="integrityData.drift_detected" class="mt-2 flex items-start gap-1 text-amber-700">
                  <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
                  <span class="text-sm">检测到内容漂移，变更文件：{{ integrityData.drifted_files.join(', ') }}</span>
                </div>
                <div v-if="integrityData.drift_check_error" class="mt-2 flex items-start gap-1 text-red-600">
                  <XCircle class="mt-0.5 h-4 w-4 shrink-0" />
                  <span class="text-sm">上次检测失败：{{ integrityData.drift_check_error }}</span>
                </div>
              </div>
              <!-- manifest 文件清单（按 category 分组） -->
              <div v-if="manifestGroups.length">
                <span class="text-gray-500">文件清单（manifest）：</span>
                <div class="mt-1 space-y-3">
                  <div v-for="group in manifestGroups" :key="group.category">
                    <div class="mb-1 text-xs font-medium text-gray-500">{{ CATEGORY_LABELS[group.category] || group.category }}</div>
                    <div class="space-y-1">
                      <div
                        v-for="file in group.files"
                        :key="file.path"
                        class="flex items-center gap-2 rounded bg-gray-50 px-2 py-1 text-xs font-mono"
                      >
                        <span class="text-gray-700 truncate">{{ file.path }}</span>
                        <span class="ml-auto shrink-0 text-gray-400">{{ formatSize(file.size) }}</span>
                        <span class="shrink-0 text-gray-400" :title="file.sha">{{ file.sha.slice(0, 8) }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </Teleport>
  </div>
</template>
