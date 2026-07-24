<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  getSkillVersions,
  createSkillVersion,
  activateSkillVersion,
  deprecateSkillVersion,
  createSkillVersionSecurityAudit,
  checkSkillVersionDrift,
  resyncSkillVersion,
  yankSkillVersion,
  listSkillTags,
  createOrMoveSkillTag,
  deleteSkillTag,
  toast,
  usePermission,
  type Skill,
  type SkillVersion,
  type SkillTag,
} from '@aihelms/shared'
import { Plus, GitBranch, MoreVertical, ChevronRight, FileText } from 'lucide-vue-next'
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
const auditTarget = ref<SkillVersion | null>(null)
const auditPolicy = ref<'balanced' | 'strict' | 'permissive'>('balanced')
const auditPolicyOptions: { v: 'balanced' | 'strict' | 'permissive'; name: string; desc: string }[] = [
  { v: 'balanced', name: '均衡策略', desc: '默认，兼顾覆盖与误报' },
  { v: 'strict', name: '严格策略', desc: '更多检查项，高风险零容忍' },
  { v: 'permissive', name: '宽松策略', desc: '仅高优先级风险检查' },
]

const tags = ref<SkillTag[]>([])
const tagTarget = ref<SkillVersion | null>(null)
const tagName = ref('')

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
    seedExpanded()
    await loadTags()
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载版本失败')
  } finally {
    loading.value = false
  }
}

async function loadTags(): Promise<void> {
  try {
    tags.value = await listSkillTags(props.skillId)
  } catch {
    tags.value = []
  }
}

function tagsForVersion(v: SkillVersion): SkillTag[] {
  return tags.value.filter((t) => t.version_id === v.id)
}

function openTagDialog(v: SkillVersion): void {
  tagTarget.value = v
  tagName.value = ''
}

async function confirmSetTag(): Promise<void> {
  if (!tagTarget.value) return
  const name = tagName.value.trim()
  if (!name) {
    toast.error('请填写标签名')
    return
  }
  try {
    await createOrMoveSkillTag(props.skillId, name, tagTarget.value.id)
    toast.success(`标签 ${name} 已设置到版本 ${tagTarget.value.version}`)
    tagName.value = ''
    await loadTags()
  } catch (e) {
    toast.error((e as { message?: string }).message || '设置标签失败')
  }
}

async function handleRemoveTag(name: string): Promise<void> {
  try {
    await deleteSkillTag(props.skillId, name)
    toast.success(`标签 ${name} 已删除`)
    await loadTags()
  } catch (e) {
    toast.error((e as { message?: string }).message || '删除标签失败')
  }
}

watch(() => props.skillId, loadVersions, { immediate: true })

function canActivate(v: SkillVersion): boolean {
  if (v.is_active || !v.protocol_valid) return false
  // 激活强制前置：必须通过安全审查（passed / attention_required）
  return (
    v.security_status === 'completed' &&
    (v.security_decision === 'passed' || v.security_decision === 'attention_required')
  )
}

const openMenuId = ref<number | null>(null)

const router = useRouter()
const expandedIds = ref<Set<number>>(new Set())

function seedExpanded(): void {
  const next = new Set<number>()
  for (const v of versions.value) {
    if (v.is_active || v.lifecycle_status === 'pending_review') next.add(v.id)
  }
  expandedIds.value = next
}

function isExpanded(v: SkillVersion): boolean {
  return expandedIds.value.has(v.id)
}

function toggleExpand(v: SkillVersion): void {
  const next = new Set(expandedIds.value)
  if (next.has(v.id)) next.delete(v.id)
  else next.add(v.id)
  expandedIds.value = next
}

function openAuditReport(v: SkillVersion): void {
  if (!v.latest_ai_policies_audit_code) return
  router.push(`/ai-policies/audits/${v.latest_ai_policies_audit_code}`)
}

type RowAction = {
  key: string
  label: string
  variant: 'primary' | 'danger' | 'warn' | 'ghost'
  disabled?: boolean
  title?: string
  run: () => void | Promise<void>
}

function variantClass(variant: RowAction['variant']): string {
  switch (variant) {
    case 'primary':
      return 'bg-green-50 text-green-600 hover:bg-green-100'
    case 'danger':
      return 'bg-red-50 text-red-600 hover:bg-red-100'
    case 'warn':
      return 'bg-amber-50 text-amber-600 hover:bg-amber-100'
    default:
      return 'bg-slate-100 text-slate-500 hover:bg-slate-200'
  }
}

function primaryActions(v: SkillVersion): RowAction[] {
  const busy = actingId.value === v.id
  if (v.lifecycle_status === 'pending_review') {
    if (canActivate(v)) {
      return [{ key: 'activate', label: busy ? '...' : '设为激活', variant: 'primary', disabled: busy, title: '设为当前激活版本(需安全审查通过 + 协议校验)', run: () => handleActivate(v) }]
    }
    return []
  }
  if (v.lifecycle_status === 'published') {
    if (v.is_active) {
      return [{ key: 'yank', label: busy ? '...' : '撤回', variant: 'danger', disabled: busy, title: '撤回此已激活版本', run: () => { yankTarget.value = v } }]
    }
    if (canActivate(v)) {
      return [{ key: 'activate', label: busy ? '...' : '设为激活', variant: 'primary', disabled: busy, title: '设为当前激活版本(需安全审查通过 + 协议校验)', run: () => handleActivate(v) }]
    }
  }
  return []
}

function overflowActions(v: SkillVersion): RowAction[] {
  const actions: RowAction[] = []
  const busy = actingId.value === v.id
  if (canManage) {
    actions.push({ key: 'tag', label: '版本别名', variant: 'ghost', run: () => openTagDialog(v) })
  }
  if (canScan && v.security_status !== 'queued' && v.security_status !== 'running') {
    actions.push({
      key: 'audit',
      label: v.security_status === 'not_scanned' ? '安全审查' : '重审',
      variant: 'ghost',
      disabled: busy,
      run: () => openAuditDialog(v),
    })
  }
  if (canManage && v.lifecycle_status === 'published' && !v.is_active) {
    actions.push({ key: 'yank', label: '撤回', variant: 'ghost', disabled: busy, run: () => { yankTarget.value = v } })
  }
  if (canManage && v.source_type === 'url') {
    actions.push({
      key: 'drift',
      label: checkingDriftId.value === v.id ? '...' : '检测漂移',
      variant: 'ghost',
      disabled: checkingDriftId.value === v.id,
      run: () => handleCheckDrift(v),
    })
  }
  if (canManage && v.source_type === 'url' && v.drift_detected) {
    actions.push({ key: 'resync', label: '重新同步', variant: 'ghost', run: () => openResync(v) })
  }
  if (canManage && !v.is_active && v.lifecycle_status !== 'deprecated') {
    actions.push({ key: 'deprecate', label: '弃用', variant: 'ghost', run: () => { deprecateTarget.value = v } })
  }
  return actions
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
      return { cls: 'bg-green-50 text-green-600', label: '可激活' }
    case 'pending_review':
      return { cls: 'bg-amber-50 text-amber-600', label: '待激活' }
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
  if (v.is_active) return { cls: 'bg-emerald-50 text-emerald-600', label: '当前激活' }
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

function openAuditDialog(v: SkillVersion): void {
  auditTarget.value = v
  auditPolicy.value = 'balanced'
}

async function confirmAudit(): Promise<void> {
  if (!auditTarget.value) return
  const target = auditTarget.value
  actingId.value = target.id
  try {
    await createSkillVersionSecurityAudit(props.skillId, target.id, auditPolicy.value)
    toast.success('已提交版本安全审查，完成后可激活')
    auditTarget.value = null
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
  <div class="mb-4 rounded-xl border border-slate-200/60 p-3">
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
        class="rounded-lg border border-slate-100 px-2.5 py-2 text-xs"
        :class="isExpanded(v) ? 'bg-white' : 'bg-slate-50/40'"
      >
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="flex min-w-0 flex-1 items-center gap-1.5 text-left"
            @click="toggleExpand(v)"
          >
            <ChevronRight
              class="h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform"
              :class="isExpanded(v) ? 'rotate-90' : ''"
            />
            <span class="font-mono font-medium text-slate-800">v{{ v.version }}</span>
            <span v-if="v.version_label" class="truncate text-slate-400">{{ v.version_label }}</span>
            <span
              v-if="v.is_active"
              class="rounded bg-emerald-50 px-1 py-0.5 text-xs font-medium text-emerald-600"
            >当前激活</span>
            <span
              class="rounded px-1.5 py-0.5 text-xs"
              :class="lifecycleBadge(v.lifecycle_status).cls"
            >{{ lifecycleBadge(v.lifecycle_status).label }}</span>
            <span
              v-if="!isExpanded(v)"
              class="rounded px-1 py-0.5 text-xs"
              :class="securityBadge(v).cls"
            >{{ securityBadge(v).label }}</span>
          </button>

          <div v-if="canManage || canScan" class="relative flex shrink-0 items-center gap-1">
            <button
              v-for="a in primaryActions(v)"
              :key="a.key"
              class="rounded px-1.5 py-0.5 text-xs disabled:cursor-not-allowed disabled:opacity-50"
              :class="variantClass(a.variant)"
              :disabled="a.disabled"
              :title="a.title"
              @click="a.run"
            >
              {{ a.label }}
            </button>
            <template v-if="overflowActions(v).length">
              <button
                class="rounded px-1 py-0.5 text-slate-500 hover:bg-slate-200"
                @click.stop="openMenuId = openMenuId === v.id ? null : v.id"
              >
                <MoreVertical class="h-3.5 w-3.5" />
              </button>
              <div
                v-if="openMenuId === v.id"
                class="absolute right-0 top-full z-20 mt-1 min-w-[8rem] rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
              >
                <button
                  v-for="a in overflowActions(v)"
                  :key="a.key"
                  class="block w-full px-3 py-1.5 text-left text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
                  :disabled="a.disabled"
                  @click="openMenuId = null; a.run()"
                >
                  {{ a.label }}
                </button>
              </div>
              <div v-if="openMenuId === v.id" class="fixed inset-0 z-10" @click="openMenuId = null" />
            </template>
          </div>
        </div>

        <div v-if="isExpanded(v)" class="mt-2 space-y-1.5 border-t border-slate-100 pt-2">
          <!-- 行1：阶段 / 安全审查 / 协议校验 -->
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="text-xs text-slate-400">阶段</span>
            <span
              class="rounded px-2 py-0.5 text-xs font-medium"
              :class="lifecycleBadge(v.lifecycle_status).cls"
            >{{ lifecycleBadge(v.lifecycle_status).label }}</span>
            <span class="ml-1 text-xs text-slate-400">安全审查</span>
            <span class="rounded px-1.5 py-0.5 text-xs" :class="securityBadge(v).cls">{{ securityBadge(v).label }}</span>
            <button
              v-if="v.latest_ai_policies_audit_code"
              type="button"
              class="inline-flex items-center gap-0.5 text-xs text-purple-600 hover:underline"
              @click="openAuditReport(v)"
            >
              <FileText class="h-3 w-3" /> 报告
            </button>
            <span
              v-if="v.security_status === 'running' || v.security_status === 'queued'"
              class="text-xs text-slate-400"
            >审查中…</span>
            <span class="ml-1 text-xs text-slate-400">协议校验</span>
            <span
              class="cursor-help rounded px-1.5 py-0.5 text-xs"
              :class="protocolBadge(v).cls"
              :title="protocolBadge(v).tip"
            >{{ protocolBadge(v).label }}</span>
          </div>

          <!-- 行2：文件 / hash / 标签 / 漂移 -->
          <div class="flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
            <span v-if="v.zip_filename" class="truncate">{{ v.zip_filename }}</span>
            <span v-else class="italic">无独立 zip</span>
            <span v-if="v.composite_hash" class="truncate font-mono text-slate-300">{{ v.composite_hash.slice(0, 8) }}</span>
            <span
              v-for="t in tagsForVersion(v)"
              :key="t.id"
              class="rounded px-1.5 py-0.5"
              :class="t.is_system ? 'bg-slate-200 text-slate-500' : 'bg-purple-50 text-purple-600'"
              :title="t.is_system ? '系统保留标签（只读，由最新已发布版本推导）' : `版本别名 → v${v.version}`"
            >{{ t.tag_name }}</span>
            <span
              v-if="driftBadge(v)"
              class="cursor-help rounded px-1.5 py-0.5"
              :class="driftBadge(v)!.cls"
              :title="driftBadge(v)!.tip"
            >{{ driftBadge(v)!.label }}</span>
          </div>

          <!-- 行3：变更说明 + 摘要 -->
          <div v-if="v.change_log || v.summary_text" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
            <span v-if="v.change_log" class="truncate">变更：{{ v.change_log }}</span>
            <span v-if="v.summary_text" class="truncate italic">{{ v.summary_text.slice(0, 80) }}{{ v.summary_text.length > 80 ? '...' : '' }}</span>
          </div>
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
      title="撤回已激活版本"
      :message="`确认撤回版本 ${yankTarget?.version}？撤回后该版本不再可用；若其为当前激活版本，将自动重算到次新可激活版本。`"
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
            <label class="mb-1 block text-xs font-medium text-slate-600">版本副标题（可选）</label>
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
          <div class="mt-1 text-xs text-slate-400">{{ createHint }}</div>
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

    <div
      v-if="auditTarget"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
    >
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-2 text-lg font-semibold text-slate-900">
          AI Policies 安全审查 · v{{ auditTarget.version }}
        </h3>
        <p class="mb-3 text-xs text-slate-500">
          选择审查策略，对版本 <span class="font-mono">v{{ auditTarget.version }}</span> 的 zip 内容执行 AI Policies 检查，通过后方可激活。
        </p>
        <div class="mb-4 space-y-2">
          <label
            v-for="opt in auditPolicyOptions"
            :key="opt.v"
            class="flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm"
            :class="auditPolicy === opt.v ? 'border-purple-400 bg-purple-50' : 'border-slate-200 hover:bg-slate-50'"
          >
            <input v-model="auditPolicy" type="radio" :value="opt.v" class="mt-0.5" />
            <span>
              <span class="font-medium text-slate-900">{{ opt.name }}</span>
              <span class="block text-xs text-slate-500">{{ opt.desc }}</span>
            </span>
          </label>
        </div>
        <div class="flex justify-end gap-2">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="auditTarget = null">取消</button>
          <button
            class="rounded-lg bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-500 disabled:opacity-50"
            :disabled="actingId === auditTarget.id"
            @click="confirmAudit()"
          >
            {{ actingId === auditTarget.id ? '提交中…' : '开始审查' }}
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="tagTarget"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
    >
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-2 text-lg font-semibold text-slate-900">
          版本标签 · v{{ tagTarget.version }}
        </h3>
        <p class="mb-3 text-xs text-slate-500">
          标签指向具体版本（如 beta/stable），同名标签设置到新版本即移动。<span class="text-slate-400">latest 为系统保留，随最新已发布版本自动更新。</span>
        </p>
        <div v-if="tagsForVersion(tagTarget).length" class="mb-3 flex flex-wrap gap-1.5">
          <span
            v-for="t in tagsForVersion(tagTarget)"
            :key="t.id"
            class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs"
            :class="t.is_system ? 'bg-slate-200 text-slate-500' : 'bg-purple-50 text-purple-600'"
          >
            {{ t.tag_name }}
            <button
              v-if="!t.is_system"
              class="text-purple-400 hover:text-purple-700"
              @click="handleRemoveTag(t.tag_name)"
            >×</button>
          </span>
        </div>
        <div class="mb-4 flex gap-2">
          <input
            v-model="tagName"
            placeholder="如 beta / stable"
            class="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none"
            @keyup.enter="confirmSetTag"
          />
          <button
            class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
            @click="confirmSetTag"
          >设置</button>
        </div>
        <div class="flex justify-end">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="tagTarget = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>
