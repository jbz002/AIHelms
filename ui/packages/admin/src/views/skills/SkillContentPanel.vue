<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  getSkillSummary,
  getSkillFull,
  getSkillIntegrity,
  usePermission,
  type SkillSummaryView,
  type SkillFullView,
  type SkillIntegrityView,
} from '@aihelms/shared'
import MarkdownRenderer from '@aihelms/shared/src/components/MarkdownRenderer.vue'
import { ChevronDown, ChevronUp, FileCheck, ShieldCheck } from 'lucide-vue-next'
import { toast } from '@aihelms/shared'

interface Props {
  skillId: number
}

const props = defineProps<Props>()
const { hasPermission } = usePermission()

type DisclosureLayer = 'overview' | 'summary' | 'full'
const activeLayer = ref<DisclosureLayer>('overview')
const summaryData = ref<SkillSummaryView | null>(null)
const fullData = ref<SkillFullView | null>(null)
const integrityData = ref<SkillIntegrityView | null>(null)
const summaryLoading = ref(false)
const fullLoading = ref(false)
const showIntegrity = ref(false)

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

async function loadIntegrity(): Promise<void> {
  if (integrityData.value) return
  try {
    integrityData.value = await getSkillIntegrity(props.skillId)
  } catch {
    toast.error('加载完整性信息失败')
  }
}

async function switchLayer(layer: DisclosureLayer): Promise<void> {
  activeLayer.value = layer
  if (layer === 'summary') await loadSummary()
  if (layer === 'full') await loadFull()
}

function toggleIntegrity(): void {
  showIntegrity.value = !showIntegrity.value
  if (showIntegrity.value) loadIntegrity()
}

function formatFrontmatterValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value ?? '')
}

const tabs: { key: DisclosureLayer; label: string }[] = [
  { key: 'overview', label: '概览' },
  { key: 'summary', label: '摘要' },
  { key: 'full', label: '完整指令' },
]

watch(
  () => props.skillId,
  () => {
    activeLayer.value = 'overview'
    summaryData.value = null
    fullData.value = null
    integrityData.value = null
    showIntegrity.value = false
  },
)
</script>

<template>
  <div class="mt-4 rounded-xl border border-gray-200 bg-white">
    <!-- Tab header -->
    <div class="flex border-b border-gray-200">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="px-4 py-2.5 text-sm font-medium transition-colors"
        :class="
          activeLayer === tab.key
            ? 'border-b-2 border-blue-500 text-blue-600'
            : 'text-gray-500 hover:text-gray-700'
        "
        @click="switchLayer(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Tab content -->
    <div class="p-4">
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

      <!-- Full: rendered markdown -->
      <div v-if="activeLayer === 'full'">
        <div v-if="fullLoading" class="py-8 text-center text-sm text-gray-400">加载中...</div>
        <div v-else-if="fullData?.full_content">
          <MarkdownRenderer :content="fullData.full_content" />
        </div>
        <div v-else class="py-8 text-center text-sm text-gray-400">
          该 Skill 无完整内容
        </div>
      </div>
    </div>

    <!-- Integrity section (admin only) -->
    <div v-if="hasPermission('skill:read')" class="border-t border-gray-200">
      <button
        class="flex w-full items-center justify-between px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
        @click="toggleIntegrity"
      >
        <span class="flex items-center gap-2">
          <ShieldCheck class="h-4 w-4" />
          内容完整性
        </span>
        <component :is="showIntegrity ? ChevronUp : ChevronDown" class="h-4 w-4" />
      </button>
      <div v-if="showIntegrity && integrityData" class="border-t border-gray-200 px-4 py-3">
        <div class="space-y-2 text-sm">
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
          <div v-if="integrityData.drift_detected" class="rounded-lg bg-amber-50 px-3 py-2 text-amber-700">
            <FileCheck class="mr-1 inline h-4 w-4" />
            检测到内容漂移，文件：{{ integrityData.drifted_files.join(', ') }}
          </div>
          <div v-if="integrityData.file_hashes && Object.keys(integrityData.file_hashes).length > 0">
            <span class="text-gray-500">文件哈希：</span>
            <div class="mt-1 space-y-1">
              <div
                v-for="(hash, path) in integrityData.file_hashes"
                :key="path"
                class="flex gap-2 rounded bg-gray-50 px-2 py-1 text-xs font-mono"
              >
                <span class="text-gray-500">{{ path }}</span>
                <span class="text-gray-700 truncate">{{ hash }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
