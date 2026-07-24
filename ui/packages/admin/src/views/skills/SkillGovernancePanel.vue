<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import {
  setSkillHidden,
  listLabelDefinitions,
  grantSkillLabel,
  revokeSkillLabel,
  listSkillLabels,
  toast,
  LabelBadge,
  type Skill,
  type LabelDefinition,
  type SkillLabelGrant,
  usePermission,
} from '@aihelms/shared'
import { Award } from 'lucide-vue-next'

interface Props {
  skill: Skill
}

const props = defineProps<Props>()
const emit = defineEmits<{
  changed: []
}>()

const { hasPermission } = usePermission()
const canManageLabel = hasPermission('skill:label:manage')

const labelDefs = ref<LabelDefinition[]>([])
const labels = ref<SkillLabelGrant[]>([])
const granting = ref(false)
const toggling = ref(false)
const grantLabelName = ref('')
const grantNote = ref('')

async function loadLabels(): Promise<void> {
  if (!canManageLabel) {
    labels.value = props.skill.labels ?? []
    return
  }
  try {
    const [defs, granted] = await Promise.all([
      listLabelDefinitions(true).catch(() => []),
      listSkillLabels(props.skill.id),
    ])
    labelDefs.value = defs
    labels.value = granted
  } catch {
    labels.value = props.skill.labels ?? []
  }
}

async function handleToggleHidden(): Promise<void> {
  toggling.value = true
  try {
    const next = !props.skill.hidden
    await setSkillHidden(props.skill.id, next)
    toast.success(next ? '已治理下架' : '已恢复上架')
    emit('changed')
  } catch (e) {
    toast.error((e as { message?: string }).message || '操作失败')
  } finally {
    toggling.value = false
  }
}

async function handleGrantLabel(): Promise<void> {
  if (!grantLabelName.value) return
  granting.value = true
  try {
    await grantSkillLabel(props.skill.id, grantLabelName.value, grantNote.value.trim())
    toast.success('治理标签已授予')
    grantLabelName.value = ''
    grantNote.value = ''
    labels.value = await listSkillLabels(props.skill.id)
  } catch (e) {
    toast.error((e as { message?: string }).message || '授予失败')
  } finally {
    granting.value = false
  }
}

async function handleRevokeLabel(name: string): Promise<void> {
  try {
    await revokeSkillLabel(props.skill.id, name)
    toast.success('治理标签已撤销')
    labels.value = await listSkillLabels(props.skill.id)
  } catch (e) {
    toast.error((e as { message?: string }).message || '撤销失败')
  }
}

watch(() => props.skill.id, loadLabels)
onMounted(loadLabels)
</script>

<template>
  <div class="mb-4 rounded-xl border border-slate-200/60 p-3">
    <h4 class="mb-3 flex items-center gap-1.5 text-sm font-semibold text-slate-900">
      <Award class="h-4 w-4 text-amber-500" />
      治理
    </h4>

    <!-- 治理下架 -->
    <div class="mb-3 flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2">
      <div>
        <p class="text-sm font-medium text-slate-700">治理下架（hidden）</p>
        <p class="text-xs text-slate-400">与发布开关、可见性正交。下架后非管理员不可见。</p>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="skill.hidden" class="rounded bg-red-50 px-1.5 py-0.5 text-[10px] text-red-600">已下架</span>
        <button
          class="rounded-md px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50"
          :class="skill.hidden ? 'bg-slate-200 text-slate-600 hover:bg-slate-300' : 'bg-red-50 text-red-600 hover:bg-red-100'"
          :disabled="toggling"
          @click="handleToggleHidden"
        >
          {{ skill.hidden ? '恢复上架' : '下架' }}
        </button>
      </div>
    </div>

    <!-- 治理标签 -->
    <div class="rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2">
      <div class="mb-2 flex items-center gap-1.5">
        <p class="text-sm font-medium text-slate-700">治理标签</p>
        <p class="text-xs text-slate-400">运营标注位（recommended/official/verified），不进质量分。</p>
      </div>
      <div v-if="labels.length" class="mb-2 flex flex-wrap items-center gap-1.5">
        <span v-for="l in labels" :key="l.id" class="inline-flex items-center gap-1">
          <LabelBadge :name="l.name" :display_name_key="l.display_name_key" :color="l.color" size="sm" />
          <button
            v-if="canManageLabel"
            class="text-slate-300 hover:text-red-500"
            title="撤销"
            @click="handleRevokeLabel(l.name)"
          >×</button>
        </span>
      </div>
      <p v-else class="mb-2 text-xs text-slate-400">暂无治理标签</p>
      <div v-if="canManageLabel" class="flex flex-wrap items-center gap-2">
        <select
          v-model="grantLabelName"
          class="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-800 focus:border-amber-500 focus:outline-none"
        >
          <option value="" disabled>选择标签</option>
          <option v-for="d in labelDefs" :key="d.id" :value="d.name">{{ d.name }}</option>
        </select>
        <input
          v-model="grantNote"
          placeholder="备注（可选）"
          class="flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-800 focus:border-amber-500 focus:outline-none"
        />
        <button
          class="rounded-md bg-amber-50 px-3 py-1 text-xs font-medium text-amber-600 hover:bg-amber-100 disabled:opacity-50"
          :disabled="!grantLabelName || granting"
          @click="handleGrantLabel"
        >
          {{ granting ? '...' : '授予' }}
        </button>
      </div>
    </div>
  </div>
</template>
