<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast, getMyAgentContributions, deleteAgentContribution, submitAgentReview } from '@aihelms/shared'
import type { Agent } from '@aihelms/shared'
import { Pencil, Trash2, Send } from 'lucide-vue-next'
import WebAgentForm from './WebAgentForm.vue'

const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()

const agents = ref<Agent[]>([])
const loading = ref(false)
const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const activeAgent = ref<Agent | null>(null)

async function load(): Promise<void> {
  loading.value = true
  try {
    const res = await getMyAgentContributions(1, 50)
    agents.value = res.items
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openCreate(): void {
  formMode.value = 'create'
  activeAgent.value = null
  formVisible.value = true
}
function openEdit(agent: Agent): void {
  formMode.value = 'edit'
  activeAgent.value = agent
  formVisible.value = true
}

async function onSaved(): Promise<void> {
  formVisible.value = false
  toast.success(t('contributor.msg.saved'))
  await load()
  emit('changed')
}

async function handleDelete(agent: Agent): Promise<void> {
  if (!window.confirm(t('contributor.deleteConfirm'))) return
  try {
    await deleteAgentContribution(agent.id)
    toast.success(t('contributor.msg.deleted'))
    await load()
    emit('changed')
  } catch (e) {
    toast.error((e as Error).message)
  }
}

async function handleSubmitReview(agent: Agent): Promise<void> {
  if (!window.confirm(t('contributor.reviewHint'))) return
  try {
    await submitAgentReview(agent.id)
    toast.success(t('contributor.msg.submitted'))
    await load()
    emit('changed')
  } catch (e) {
    toast.error((e as Error).message)
  }
}

defineExpose({ refresh: load })
</script>

<template>
  <div>
    <div class="mb-3 flex justify-end">
      <button class="flex items-center gap-1.5 rounded-lg bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-700" @click="openCreate">
        {{ t('contributor.btn.create') }}
      </button>
    </div>
    <div v-if="!loading && !agents.length" class="rounded-xl border border-dashed border-slate-200 bg-white p-12 text-center text-sm text-slate-400">
      {{ t('contributor.empty') }}
    </div>
    <div v-else class="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table class="w-full text-sm">
        <thead class="bg-slate-50 text-left text-xs text-slate-500">
          <tr>
            <th class="px-4 py-3">{{ t('contributor.col.name') }}</th>
            <th class="px-4 py-3">{{ t('contributor.col.platform') }}</th>
            <th class="px-4 py-3">{{ t('contributor.col.category') }}</th>
            <th class="px-4 py-3">{{ t('contributor.col.status') }}</th>
            <th class="px-4 py-3">{{ t('contributor.col.updated') }}</th>
            <th class="px-4 py-3 text-right">{{ t('contributor.col.actions') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-for="agent in agents" :key="agent.id" class="hover:bg-slate-50">
            <td class="px-4 py-3 font-medium text-slate-800">{{ agent.name }}</td>
            <td class="px-4 py-3 text-slate-600">{{ agent.platform }}</td>
            <td class="px-4 py-3 text-slate-600">{{ agent.category }}</td>
            <td class="px-4 py-3">
              <span class="rounded-full px-2 py-0.5 text-xs" :class="agent.is_published ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'">
                {{ agent.is_published ? t('contributor.status.published') : t('contributor.status.draft') }}
              </span>
            </td>
            <td class="px-4 py-3 text-slate-500">{{ agent.updated_at?.slice(0, 10) }}</td>
            <td class="px-4 py-3">
              <div class="flex items-center justify-end gap-1">
                <button :title="t('contributor.action.edit')" class="rounded p-1.5 text-slate-500 hover:bg-slate-100" @click="openEdit(agent)"><Pencil class="h-4 w-4" /></button>
                <button v-if="!agent.is_published" :title="t('contributor.action.submitReview')" class="rounded p-1.5 text-purple-500 hover:bg-purple-50" @click="handleSubmitReview(agent)"><Send class="h-4 w-4" /></button>
                <button v-if="!agent.is_published" :title="t('contributor.action.delete')" class="rounded p-1.5 text-red-500 hover:bg-red-50" @click="handleDelete(agent)"><Trash2 class="h-4 w-4" /></button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <WebAgentForm :visible="formVisible" :mode="formMode" :agent="activeAgent" @close="formVisible = false" @saved="onSaved" />
  </div>
</template>
