<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuth, usePermission } from '@aihelms/shared'
import ContributorSkillPanel from '../components/ContributorSkillPanel.vue'
import ContributorMcpPanel from '../components/ContributorMcpPanel.vue'
import ContributorAgentPanel from '../components/ContributorAgentPanel.vue'

const { t } = useI18n()
const { currentUser, fetchCurrentUser } = useAuth()
const { hasPermission } = usePermission()

type TabKey = 'skill' | 'mcp' | 'agent'

const tabs = computed(() => {
  const list: { key: TabKey; labelKey: string }[] = []
  if (hasPermission('skill:contribute')) list.push({ key: 'skill', labelKey: 'contributor.tab.skill' })
  if (hasPermission('mcp:contribute')) list.push({ key: 'mcp', labelKey: 'contributor.tab.mcp' })
  if (hasPermission('agent:contribute')) list.push({ key: 'agent', labelKey: 'contributor.tab.agent' })
  return list
})

const activeTab = ref<TabKey | null>(null)

function ensureActiveTab(): void {
  if (activeTab.value && tabs.value.some((tab) => tab.key === activeTab.value)) return
  activeTab.value = tabs.value.length ? tabs.value[0].key : null
}

if (!currentUser.value) {
  fetchCurrentUser().then(ensureActiveTab)
} else {
  ensureActiveTab()
}

const canContribute = computed(() => tabs.value.length > 0)
</script>

<template>
  <div class="mx-auto max-w-5xl px-6 py-8">
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-slate-900">{{ t('contributor.title') }}</h1>
      <p class="mt-1 text-sm text-slate-500">{{ t('contributor.subtitle') }}</p>
    </div>

    <div v-if="!canContribute" class="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-700">
      {{ t('contributor.msg.noPermission') }}
    </div>

    <template v-else>
      <div class="mb-4 flex gap-1 border-b border-slate-200">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="-mb-px border-b-2 px-4 py-2 text-sm transition-colors"
          :class="activeTab === tab.key ? 'border-purple-600 font-medium text-purple-700' : 'border-transparent text-slate-500 hover:text-slate-700'"
          @click="activeTab = tab.key"
        >
          {{ t(tab.labelKey) }}
        </button>
      </div>

      <ContributorSkillPanel v-if="activeTab === 'skill'" />
      <ContributorMcpPanel v-else-if="activeTab === 'mcp'" />
      <ContributorAgentPanel v-else-if="activeTab === 'agent'" />
    </template>
  </div>
</template>
