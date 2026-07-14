<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@aihelms/shared/src/api/request'
import { getSkillSummary, getSkillFull, toast } from '@aihelms/shared'
import type { Skill, SkillSummaryView, SkillFullView } from '@aihelms/shared'
import MarkdownRenderer from '@aihelms/shared/src/components/MarkdownRenderer.vue'
import { X, ChevronDown, Flame } from 'lucide-vue-next'

interface SkillInstallInfo {
  name: string
  description: string
  agent_prompt: string
  download_url: string
  usage_instructions: string
  author?: string
}

interface Props {
  visible: boolean
  skill: Skill
}

const props = defineProps<Props>()
const emit = defineEmits<{
  close: []
}>()

const { t } = useI18n()

const loading = ref(false)
const installInfo = ref<SkillInstallInfo | null>(null)
const promptCopied = ref(false)
const summaryData = ref<SkillSummaryView | null>(null)
const fullData = ref<SkillFullView | null>(null)
const summaryLoading = ref(false)
const fullLoading = ref(false)
const showContent = ref(false)

type ContentDepth = 'card' | 'summary' | 'full'

async function loadInstallInfo(): Promise<void> {
  loading.value = true
  try {
    installInfo.value = await request<SkillInstallInfo>(`/api/v1/skills/${props.skill.id}/install-info`)
  } catch {
    /* ignore */
  } finally {
    loading.value = false
  }
}

async function copyPrompt(): Promise<void> {
  if (!installInfo.value) return
  try {
    await navigator.clipboard.writeText(installInfo.value.agent_prompt)
    promptCopied.value = true
    setTimeout(() => {
      promptCopied.value = false
    }, 2000)
  } catch {
    toast.error('复制失败')
  }
}

async function loadSummary(): Promise<void> {
  if (summaryData.value) {
    showContent.value = true
    return
  }
  summaryLoading.value = true
  try {
    summaryData.value = await getSkillSummary(props.skill.id)
    showContent.value = true
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
    fullData.value = await getSkillFull(props.skill.id)
  } catch {
    toast.error('加载完整内容失败')
  } finally {
    fullLoading.value = false
  }
}

watch(() => props.visible, (v) => {
  if (v && props.skill) {
    loadInstallInfo()
  }
})

watch(
  () => props.skill.id,
  () => {
    summaryData.value = null
    fullData.value = null
    showContent.value = false
  },
)
</script>

<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      @click.self="emit('close')"
    >
      <div class="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border border-slate-200/60 bg-white shadow-xl">
        <!-- Header -->
        <div class="flex items-center justify-between gap-4 border-b border-slate-100 px-6 py-4">
          <div class="flex min-w-0 items-center gap-2">
            <h3 class="truncate text-lg font-semibold text-slate-800">{{ skill.name }}</h3>
            <span v-if="installInfo?.author" class="max-w-[6em] shrink-0 truncate text-xs text-slate-400">{{ installInfo.author }}</span>
            <span class="flex shrink-0 items-center gap-1 text-xs text-slate-400 tabular-nums">
              <Flame class="h-3.5 w-3.5 text-orange-500" />
              {{ skill.install_count ?? 0 }}
            </span>
          </div>
          <button class="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" @click="emit('close')">
            <X class="h-5 w-5" />
          </button>
        </div>

        <!-- Body -->
        <div class="flex-1 overflow-y-auto px-6 py-5">
          <div v-if="loading" class="flex items-center justify-center py-10">
            <div class="h-6 w-6 animate-spin rounded-full border-2 border-purple-500 border-t-transparent" />
          </div>

          <template v-else-if="installInfo">
            <!-- Description -->
            <p v-if="installInfo.description" class="mb-4 whitespace-pre-wrap text-sm leading-relaxed text-slate-600">
              {{ installInfo.description }}
            </p>

            <!-- Agent Prompt -->
            <div class="mb-4">
              <label class="mb-2 block text-xs font-semibold text-slate-700">
                {{ t('market.skill.agentPrompt') }}
              </label>
              <div class="rounded-lg bg-slate-900 p-4">
                <pre class="whitespace-pre-wrap text-xs leading-relaxed text-green-300">{{ installInfo.agent_prompt }}</pre>
              </div>
              <button
                class="mt-2 rounded-lg bg-gradient-to-r from-purple-500 to-blue-500 px-4 py-1.5 text-xs font-medium text-white shadow-sm"
                @click="copyPrompt"
              >
                {{ promptCopied ? t('market.install.copied') : t('market.skill.copyPrompt') }}
              </button>
            </div>

            <!-- Usage Instructions -->
            <div v-if="installInfo.usage_instructions">
              <label class="mb-2 block text-xs font-semibold text-slate-700">{{ t('market.install.instructions') }}</label>
              <div class="rounded-lg bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-700 whitespace-pre-wrap">
                {{ installInfo.usage_instructions }}
              </div>
            </div>

            <!-- Progressive disclosure: view details / expand full -->
            <div class="mt-4 border-t border-slate-100 pt-4">
              <button
                v-if="!showContent"
                class="flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 transition-colors hover:bg-slate-50"
                @click="loadSummary"
              >
                <ChevronDown class="h-4 w-4" />
                {{ summaryLoading ? t('market.skill.loading') : t('market.skill.viewDetails') }}
              </button>
              <template v-else>
                <!-- Summary -->
                <div class="mb-3">
                  <h4 class="mb-2 text-xs font-semibold text-slate-500">{{ t('market.skill.summary') }}</h4>
                  <div v-if="summaryLoading" class="py-4 text-center text-sm text-slate-400">{{ t('market.skill.loading') }}</div>
                  <MarkdownRenderer v-else-if="summaryData?.summary_text" :content="summaryData.summary_text" />
                  <p v-else class="text-sm text-slate-400">{{ t('market.skill.noContent') }}</p>
                </div>

                <!-- Full content toggle -->
                <button
                  class="flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 transition-colors hover:bg-slate-50"
                  @click="loadFull"
                >
                  {{ fullLoading ? t('market.skill.loading') : t('market.skill.expandFull') }}
                </button>
                <div v-if="fullData?.full_content && !fullLoading" class="mt-3">
                  <MarkdownRenderer :content="fullData.full_content" />
                </div>
              </template>
            </div>
          </template>
        </div>

        <!-- Footer -->
        <div class="flex justify-end border-t border-slate-100 px-6 py-3">
          <button class="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100" @click="emit('close')">
            {{ t('market.action.close') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
