<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import {
  getSkillVersions,
  createSkillVersion,
  activateSkillVersion,
  deprecateSkillVersion,
  createSkillVersionSecurityAudit,
  checkSkillVersionDrift,
  resyncSkillVersion,
  yankSkillVersion,
  submitSkillVersionReview,
  approveSkillVersionReview,
  rejectSkillVersionReview,
  withdrawSkillVersionReview,
  toast,
  usePermission,
  type Skill,
  type SkillVersion,
} from '@aihelms/shared'
import { Plus, GitBranch, CheckCircle2, AlertTriangle, Archive, ShieldCheck } from 'lucide-vue-next'
import ConfirmDialog from '../../components/ConfirmDialog.vue'

interface Props {
  skillId: number
  activeVersion?: SkillVersion | null
}
const props = defineProps<Props>()
const emit = defineEmits<{
  activated: [skill: Skill]
}>()

const { hasPermission } = usePermission()
const canManage = hasPermission('skill:update') || hasPermission('skill:create')
const canScan = hasPermission('ai_policies:scan')

const versions = ref<SkillVersion[]>([])
const loading = ref(false)
const actingId = ref<number | null>(null)
const showCreate = ref(false)
const deprecateTarget = ref<SkillVersion | null>(null)
const yankTarget = ref<SkillVersion | null>(null)
const checkingDriftId = ref<number | null>(null)
const resyncTarget = ref<SkillVersion | null>(null)
const resyncVersion = ref('')

const form = ref({
  version: '',
  version_label: '',
  change_log: '',
})
const zipFile = ref<File | null>(null)
const zipFileError = ref('')

// 镜像服务端 SKILLS_PACKAGE_MAX_TOTAL_SIZE_MB 默认值；服务端为准
const MAX_ZIP_SIZE = 100 * 1024 * 1024

async function loadVersions(): Promise<void> {
  if (!props.skillId) return
  loading.value = true
  try {
    versions.value = await getSkillVersions(props.skillId, true)
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载版本失败')
  } finally {
    loading.value = false
  }
}

watch(() => props.skillId, loadVersions, { immediate: true })

function canActivate(v: SkillVersion): boolean {
  if (v.is_active || !v.protocol_valid) return false
  const securityOk =
    v.security_status === 'completed' &&
    (v.security_decision === 'passed' || v.security_decision === 'attention_required')
  // pending_review：已提交审核，若已通过则可激活（最终由后端门控判定）
  return securityOk || v.lifecycle_status === 'pending_review'
}

function protocolBadge(v: SkillVersion): { cls: string; label: string; tip: string } {
  if (v.protocol_valid) {
    const warnCount = (v.protocol_errors ?? []).filter((i) => i.severity === 'warning').length
    return {
      cls: warnCount > 0 ? 'bg-amber-50 text-amber-600' : 'bg-emerald-50 text-emerald-600',
      label: warnCount > 0 ? `协议告警 ${warnCount}` : '协议合规',
      tip: warnCount > 0
        ? (v.protocol_errors ?? []).filter((i) => i.severity === 'warning').map((i) => i.message).join('；')
        : 'SKILL.md 协议校验通过',
    }
  }
  const errs = (v.protocol_errors ?? []).filter((i) => i.severity === 'error').map((i) => i.message)
  return {
    cls: 'bg-red-50 text-red-600',
    label: '协议不合规',
    tip: errs.join('；') || '存在协议合规错误，不可激活',
  }
}

function lifecycleBadge(s: string): { cls: string; label: string } {
  switch (s) {
    case 'published':
      return { cls: 'bg-green-50 text-green-600', label: '已发布' }
    case 'pending_review':
      return { cls: 'bg-amber-50 text-amber-600', label: '待审核' }
    case 'scanning':
      return { cls: 'bg-indigo-50 text-indigo-600', label: '扫描中' }
    case 'yanked':
      return { cls: 'bg-red-50 text-red-600', label: '已撤回' }
    case 'rejected':
      return { cls: 'bg-red-50 text-red-600', label: '已拒绝' }
    case 'deprecated':
      return { cls: 'bg-slate-100 text-slate-400 line-through', label: '已弃用' }
    case 'draft':
    default:
      return { cls: 'bg-slate-100 text-slate-500', label: '草稿' }
  }
}

function securityBadge(v: SkillVersion): { cls: string; label: string } {
  if (v.is_active) return { cls: 'bg-emerald-50 text-emerald-600', label: '已上线' }
  if (v.security_status === 'queued' || v.security_status === 'running') {
    return { cls: 'bg-indigo-50 text-indigo-600', label: '审查中' }
  }
  if (v.security_status === 'completed') {
    if (v.security_decision === 'passed') return { cls: 'bg-emerald-50 text-emerald-600', label: '审查通过' }
    if (v.security_decision === 'attention_required') return { cls: 'bg-amber-50 text-amber-600', label: '建议修改' }
    if (v.security_decision === 'high_risk') return { cls: 'bg-red-50 text-red-600', label: '高风险' }
  }
  if (v.security_status === 'failed') return { cls: 'bg-stone-100 text-stone-600', label: '审查失败' }
  return { cls: 'bg-slate-100 text-slate-500', label: '未审查' }
}

async function handleActivate(v: SkillVersion): Promise<void> {
  actingId.value = v.id
  try {
    const skill = await activateSkillVersion(props.skillId, v.id)
    toast.success(`已激活版本 ${v.version}`)
    emit('activated', skill)
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '激活失败')
  } finally {
    actingId.value = null
  }
}

async function handleAudit(v: SkillVersion): Promise<void> {
  actingId.value = v.id
  try {
    await createSkillVersionSecurityAudit(props.skillId, v.id)
    toast.success('已提交版本安全审查，完成后可激活')
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '审查任务创建失败')
  } finally {
    actingId.value = null
  }
}

async function confirmDeprecate(): Promise<void> {
  if (!deprecateTarget.value) return
  const target = deprecateTarget.value
  actingId.value = target.id
  try {
    await deprecateSkillVersion(props.skillId, target.id)
    toast.success(`已弃用版本 ${target.version}`)
    deprecateTarget.value = null
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '弃用失败')
  } finally {
    actingId.value = null
  }
}

function openCreate(): void {
  form.value = { version: '', version_label: '', change_log: '' }
  zipFile.value = null
  zipFileError.value = ''
  showCreate.value = true
}

async function handleCheckDrift(v: SkillVersion): Promise<void> {
  checkingDriftId.value = v.id
  try {
    await checkSkillVersionDrift(props.skillId, v.id)
    toast.success('漂移检测完成')
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '漂移检测失败')
  } finally {
    checkingDriftId.value = null
  }
}

function openResync(v: SkillVersion): void {
  resyncTarget.value = v
  resyncVersion.value = ''
}

async function confirmResync(): Promise<void> {
  if (!resyncTarget.value) return
  const target = resyncTarget.value
  actingId.value = target.id
  try {
    await resyncSkillVersion(
      props.skillId,
      target.id,
      resyncVersion.value.trim() || undefined,
    )
    toast.success('已创建新版本，请完成安全审查后再激活')
    resyncTarget.value = null
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '重新同步失败')
  } finally {
    actingId.value = null
  }
}

async function confirmYank(): Promise<void> {
  if (!yankTarget.value) return
  const target = yankTarget.value
  actingId.value = target.id
  try {
    const skill = await yankSkillVersion(props.skillId, target.id)
    toast.success(`已撤回版本 ${target.version}`)
    emit('activated', skill)
    yankTarget.value = null
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '撤回失败')
  } finally {
    actingId.value = null
  }
}

async function handleSubmitReview(v: SkillVersion): Promise<void> {
  actingId.value = v.id
  try {
    await submitSkillVersionReview(props.skillId, v.id)
    toast.success('已提交审核')
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '提交审核失败')
  } finally {
    actingId.value = null
  }
}

async function handleApproveReview(v: SkillVersion): Promise<void> {
  actingId.value = v.id
  try {
    await approveSkillVersionReview(props.skillId, v.id)
    toast.success('审核已通过，可激活上线')
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '通过失败')
  } finally {
    actingId.value = null
  }
}

async function handleRejectReview(v: SkillVersion): Promise<void> {
  actingId.value = v.id
  try {
    await rejectSkillVersionReview(props.skillId, v.id)
    toast.success('已拒绝审核')
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '拒绝失败')
  } finally {
    actingId.value = null
  }
}

async function handleWithdrawReview(v: SkillVersion): Promise<void> {
  actingId.value = v.id
  try {
    await withdrawSkillVersionReview(props.skillId, v.id)
    toast.success('已撤回审核')
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '撤回失败')
  } finally {
    actingId.value = null
  }
}

function driftBadge(
  v: SkillVersion,
): { cls: string; label: string; tip: string } | null {
  if (v.source_type !== 'url') return null
  if (v.drift_detected) {
    return {
      cls: 'bg-red-50 text-red-600',
      label: '内容漂移',
      tip: `变更文件：${(v.drifted_files ?? []).join(', ') || '—'}`,
    }
  }
  if (v.drift_check_error) {
    return { cls: 'bg-amber-50 text-amber-600', label: '检测失败', tip: v.drift_check_error }
  }
  if (v.last_drift_check_at) {
    return {
      cls: 'bg-slate-100 text-slate-500',
      label: '已检测',
      tip: `上次检测：${new Date(v.last_drift_check_at).toLocaleString()}`,
    }
  }
  return { cls: 'bg-slate-100 text-slate-400', label: '待检测', tip: '尚未执行漂移检测' }
}

function handleZipChange(event: Event): void {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0] || null
  zipFileError.value = ''
  if (file) {
    if (!file.name.toLowerCase().endsWith('.zip')) {
      zipFileError.value = '请上传 .zip 文件'
      zipFile.value = null
      return
    }
    if (file.size > MAX_ZIP_SIZE) {
      zipFileError.value = `文件超过 ${MAX_ZIP_SIZE / 1024 / 1024} MB 上限`
      zipFile.value = null
      return
    }
  }
  zipFile.value = file
}

async function handleCreate(): Promise<void> {
  if (!form.value.version.trim()) {
    toast.error('请填写版本号')
    return
  }
  if (zipFileError.value) {
    toast.error(zipFileError.value)
    return
  }
  try {
    await createSkillVersion(props.skillId, {
      version: form.value.version.trim(),
      version_label: form.value.version_label.trim(),
      change_log: form.value.change_log.trim(),
      zip_file: zipFile.value,
    })
    toast.success('版本创建成功（未激活，需通过安全审查后才可激活）')
    showCreate.value = false
    await loadVersions()
  } catch (e) {
    toast.error((e as { message?: string }).message || '创建失败')
  }
}

const createHint = computed(() => (zipFile.value ? `已选择：${zipFile.value.name}` : '不上传则沿用当前 active 内容作为新版本起点'))
</script>

<template>
  <div class="rounded-xl border border-slate-200/60 p-3">
    <div class="mb-2 flex items-center justify-between">
      <h4 class="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
        <GitBranch class="h-4 w-4 text-purple-500" /> 版本管理
      </h4>
      <button
        v-if="canManage"
        class="flex items-center gap-1 rounded-md bg-purple-50 px-2 py-1 text-xs font-medium text-purple-600 transition-colors hover:bg-purple-100"
        @click="openCreate"
      >
        <Plus class="h-3 w-3" /> 新版本
      </button>
    </div>

    <div v-if="loading" class="py-4 text-center text-xs text-slate-400">加载中...</div>
    <div v-else-if="versions.length === 0" class="py-4 text-center text-xs text-slate-400">暂无版本</div>
    <div v-else class="space-y-1.5">
      <div
        v-for="v in versions"
        :key="v.id"
        class="flex items-center gap-2 rounded-lg border border-slate-100 px-2.5 py-2 text-xs"
      >
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-1.5">
            <span class="font-mono font-medium text-slate-800">v{{ v.version }}</span>
            <span v-if="v.version_label" class="truncate text-slate-400">{{ v.version_label }}</span>
          </div>
          <div class="mt-0.5 flex items-center gap-1.5 text-slate-400">
            <span v-if="v.zip_filename" class="truncate">{{ v.zip_filename }}</span>
            <span v-else class="italic">无独立 zip</span>
            <span v-if="v.change_log" class="truncate">· {{ v.change_log }}</span>
            <span
              class="cursor-help rounded px-1 py-0.5 text-[10px]"
              :class="protocolBadge(v).cls"
              :title="protocolBadge(v).tip"
            >{{ protocolBadge(v).label }}</span>
            <span v-if="v.composite_hash" class="truncate text-slate-300 font-mono text-[10px]">{{ v.composite_hash.slice(0, 8) }}</span>
          </div>
          <div v-if="v.summary_text" class="mt-0.5 truncate text-slate-400 italic">{{ v.summary_text.slice(0, 80) }}{{ v.summary_text.length > 80 ? '...' : '' }}</div>
        </div>
        <span class="shrink-0 rounded px-1.5 py-0.5 text-[10px]" :class="lifecycleBadge(v.lifecycle_status).cls">
          {{ lifecycleBadge(v.lifecycle_status).label }}
        </span>
        <span class="shrink-0 rounded px-1.5 py-0.5 text-[10px]" :class="securityBadge(v).cls">
          {{ securityBadge(v).label }}
        </span>
        <span
          v-if="driftBadge(v)"
          class="shrink-0 cursor-help rounded px-1.5 py-0.5 text-[10px]"
          :class="driftBadge(v)!.cls"
          :title="driftBadge(v)!.tip"
        >{{ driftBadge(v)!.label }}</span>
        <div v-if="canManage || canScan" class="flex shrink-0 gap-1">
          <button
            v-if="canScan && !v.is_active && v.security_status !== 'queued' && v.security_status !== 'running'"
            class="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-600 hover:bg-indigo-100 disabled:opacity-50"
            :disabled="actingId === v.id"
            @click="handleAudit(v)"
          >
            <ShieldCheck class="mr-0.5 inline h-3 w-3" />{{ actingId === v.id ? '...' : v.security_status === 'not_scanned' ? '审查' : '重审' }}
          </button>
          <button
            v-if="canManage && !v.is_active"
            class="rounded bg-green-50 px-1.5 py-0.5 text-[10px] text-green-600 hover:bg-green-100 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="actingId === v.id || !canActivate(v)"
            :title="!canActivate(v) ? '需先通过协议校验 + 安全审查（通过/建议修改）才能激活' : ''"
            @click="handleActivate(v)"
          >
            {{ actingId === v.id ? '...' : '激活' }}
          </button>
          <button
            v-if="canManage && (v.lifecycle_status === 'draft' || v.lifecycle_status === 'scanning')"
            class="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600 hover:bg-amber-100 disabled:opacity-50"
            :disabled="actingId === v.id"
            @click="handleSubmitReview(v)"
          >
            {{ actingId === v.id ? '...' : '提交审核' }}
          </button>
          <button
            v-if="canManage && v.lifecycle_status === 'pending_review'"
            class="rounded bg-green-50 px-1.5 py-0.5 text-[10px] text-green-600 hover:bg-green-100 disabled:opacity-50"
            :disabled="actingId === v.id"
            @click="handleApproveReview(v)"
          >
            {{ actingId === v.id ? '...' : '通过' }}
          </button>
          <button
            v-if="canManage && v.lifecycle_status === 'pending_review'"
            class="rounded bg-red-50 px-1.5 py-0.5 text-[10px] text-red-600 hover:bg-red-100 disabled:opacity-50"
            :disabled="actingId === v.id"
            @click="handleRejectReview(v)"
          >
            {{ actingId === v.id ? '...' : '拒绝' }}
          </button>
          <button
            v-if="canManage && v.lifecycle_status === 'pending_review'"
            class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-200 disabled:opacity-50"
            :disabled="actingId === v.id"
            @click="handleWithdrawReview(v)"
          >
            {{ actingId === v.id ? '...' : '撤回审核' }}
          </button>
          <button
            v-if="canManage && v.lifecycle_status === 'published'"
            class="rounded bg-red-50 px-1.5 py-0.5 text-[10px] text-red-600 hover:bg-red-100 disabled:opacity-50"
            :disabled="actingId === v.id"
            @click="yankTarget = v"
          >
            撤回
          </button>
          <button
            v-if="canManage && !v.is_active && v.lifecycle_status !== 'deprecated'"
            class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-200"
            @click="deprecateTarget = v"
          >
            弃用
          </button>
          <button
            v-if="canManage && v.source_type === 'url'"
            class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-200 disabled:opacity-50"
            :disabled="checkingDriftId === v.id"
            @click="handleCheckDrift(v)"
          >
            {{ checkingDriftId === v.id ? '...' : '检测漂移' }}
          </button>
          <button
            v-if="canManage && v.source_type === 'url' && v.drift_detected"
            class="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600 hover:bg-amber-100"
            @click="openResync(v)"
          >
            重新同步
          </button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :visible="!!deprecateTarget"
      title="弃用版本"
      :message="`确认弃用版本 ${deprecateTarget?.version}？弃用版本永不可被激活。`"
      @confirm="confirmDeprecate"
      @cancel="deprecateTarget = null"
    />

    <ConfirmDialog
      :visible="!!yankTarget"
      title="撤回已发布版本"
      :message="`确认撤回版本 ${yankTarget?.version}？撤回后该版本不再可用；若其为当前发布版本，将自动重算到次新已发布版本。`"
      @confirm="confirmYank"
      @cancel="yankTarget = null"
    />

    <div
      v-if="showCreate"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
    >
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">创建新版本</h3>
        <div class="mb-3 grid grid-cols-2 gap-3">
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-600">版本号 *</label>
            <input v-model="form.version" placeholder="如 2.0.0" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-600">标签（可选）</label>
            <input v-model="form.version_label" placeholder="如 2026-07 灰度" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none" />
          </div>
        </div>
        <div class="mb-3">
          <label class="mb-1 block text-xs font-medium text-slate-600">上传 zip 包</label>
          <input
            type="file"
            accept=".zip"
            class="block w-full text-xs text-slate-700 file:mr-3 file:rounded-md file:border-0 file:bg-purple-50 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-purple-700 hover:file:bg-purple-100"
            @change="handleZipChange"
          />
          <p v-if="zipFileError" class="mt-1 text-xs text-red-500">{{ zipFileError }}</p>
          <div class="mt-1 text-[11px] text-slate-400">{{ createHint }}</div>
        </div>
        <div class="mb-4">
          <label class="mb-1 block text-xs font-medium text-slate-600">变更说明</label>
          <textarea v-model="form.change_log" rows="2" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none" />
        </div>
        <div class="flex justify-end gap-3">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="showCreate = false">取消</button>
          <button class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700" @click="handleCreate">创建</button>
        </div>
      </div>
    </div>

    <div
      v-if="resyncTarget"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
    >
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-2 text-lg font-semibold text-slate-900">重新同步漂移版本</h3>
        <p class="mb-3 text-sm text-slate-500">
          将重新拉取版本 <span class="font-mono">v{{ resyncTarget.version }}</span> 的源内容并作为新版本入库。新版本需通过安全审查后才能激活。
        </p>
        <div class="mb-4">
          <label class="mb-1 block text-xs font-medium text-slate-600">新版本号（留空自动 +patch）</label>
          <input
            v-model="resyncVersion"
            placeholder="如 1.0.1"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-amber-500 focus:outline-none"
          />
        </div>
        <div class="flex justify-end gap-3">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="resyncTarget = null">取消</button>
          <button
            class="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
            :disabled="actingId === resyncTarget.id"
            @click="confirmResync"
          >
            {{ actingId === resyncTarget.id ? '同步中…' : '确认重新同步' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
