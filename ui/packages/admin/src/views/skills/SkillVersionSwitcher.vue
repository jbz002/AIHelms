<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import {
  getSkillVersions,
  createSkillVersion,
  activateSkillVersion,
  deprecateSkillVersion,
  checkSkillVersionDrift,
  resyncSkillVersion,
  yankSkillVersion,
  restoreSkillVersion,
  listSkillTags,
  createOrMoveSkillTag,
  deleteSkillTag,
  toast,
  usePermission,
  type Skill,
  type SkillVersion,
  type SkillTag,
} from '@aihelms/shared'
import { Plus, MoreVertical } from 'lucide-vue-next'
import ConfirmDialog from '../../components/ConfirmDialog.vue'

interface Props {
  skillId: number
  activeVersion: SkillVersion | null
}
const props = defineProps<Props>()
const emit = defineEmits<{
  select: [version: SkillVersion | null]
  activated: [skill: Skill]
}>()

const { hasPermission } = usePermission()
const canManage = hasPermission('skill:update') || hasPermission('skill:create')

const versions = ref<SkillVersion[]>([])
const selectedVersion = ref<SkillVersion | null>(null)
const loading = ref(false)
const actingId = ref<number | null>(null)
const checkingDriftId = ref<number | null>(null)
const openMenu = ref(false)

const tags = ref<SkillTag[]>([])

const showCreate = ref(false)
const deprecateTarget = ref<SkillVersion | null>(null)
const yankTarget = ref<SkillVersion | null>(null)
const resyncTarget = ref<SkillVersion | null>(null)
const resyncVersion = ref('')
const tagTarget = ref<SkillVersion | null>(null)
const tagName = ref('')

const form = ref({ version: '', version_label: '', change_log: '' })
const zipFile = ref<File | null>(null)
const zipFileError = ref('')
// 镜像服务端 SKILLS_PACKAGE_MAX_TOTAL_SIZE_MB 默认值；服务端为准
const MAX_ZIP_SIZE = 100 * 1024 * 1024

async function loadVersions(
  preserve = false,
  selectId: number | null = null,
  withTags = true,
): Promise<void> {
  if (!props.skillId) return
  // 快照发起时的 skillId：切换 skill 后旧请求若晚于新请求完成，会 emit 旧 skill
  // 的 version 串到新 skill → 后端归属校验 404。完成时校验，过期则丢弃不 emit。
  const reqSkillId = props.skillId
  loading.value = true
  try {
    // versions 与 tags 独立并行；withTags=false 用于轮询（tags 不随 security_status 变）
    const [data] = await Promise.all([
      getSkillVersions(reqSkillId, true),
      withTags ? loadTags() : Promise.resolve(),
    ])
    if (props.skillId !== reqSkillId) return
    versions.value = data
    if (selectId !== null) syncSelected(selectId)
    else if (preserve) syncSelected(selectedVersion.value?.id ?? null)
    else syncSelected(props.activeVersion?.id ?? null)
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载版本失败')
  } finally {
    if (props.skillId === reqSkillId) loading.value = false
  }
}

async function loadTags(): Promise<void> {
  try {
    tags.value = await listSkillTags(props.skillId)
  } catch {
    tags.value = []
  }
}

// 选中版本同步：按 matchId 在 versions 查找，未命中或 matchId=null → fallback 首个。
// 仅在 loadVersions 内调用（versions 已校验属当前 skill，不串值）。
// matchId 来源：切 skill/初次=activeVersion.id；操作后重载=当前选中 id；创建/resync=新版本 id。
function syncSelected(matchId: number | null): void {
  if (versions.value.length === 0) {
    selectedVersion.value = null
    emit('select', null)
    return
  }
  const found = matchId !== null ? versions.value.find((v) => v.id === matchId) : undefined
  const next = found ?? versions.value[0]
  selectedVersion.value = next
  emit('select', next)
}

// 只监听 skillId：切 skill / activate 等场景都经 loadVersions → 内部 syncSelectedFromActive。
// 不单独 watch activeVersion.id：切 skill 时 active_version 已变但 versions 尚未刷新，
// 此时 sync 会用过期 versions fallback 出旧 skill 的 version 串到新 skill → 后端 404。
watch(() => props.skillId, () => loadVersions(), { immediate: true })

function onSelectChange(e: Event): void {
  openMenu.value = false
  const id = Number((e.target as HTMLSelectElement).value)
  const v = versions.value.find((x) => x.id === id) || null
  selectedVersion.value = v
  emit('select', v)
}

function tagsForVersion(v: SkillVersion): SkillTag[] {
  return tags.value.filter((t) => t.version_id === v.id)
}

// 激活前置：协议合规 + 安全审查通过/建议修改
function canActivate(v: SkillVersion): boolean {
  if (v.is_active || !v.protocol_valid) return false
  return (
    v.security_status === 'completed' &&
    (v.security_decision === 'passed' || v.security_decision === 'attention_required')
  )
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
      return [
        {
          key: 'activate',
          label: busy ? '...' : '设为激活',
          variant: 'primary',
          disabled: busy,
          title: '设为当前激活版本(需安全审查通过 + 协议校验)',
          run: () => handleActivate(v),
        },
      ]
    }
    return []
  }
  if (v.lifecycle_status === 'yanked') {
    return [
      { key: 'restore', label: busy ? '...' : '恢复', variant: 'primary', disabled: busy, run: () => handleRestore(v) },
    ]
  }
  if (v.lifecycle_status === 'published') {
    if (v.is_active) {
      return [
        { key: 'yank', label: busy ? '...' : '撤回', variant: 'danger', disabled: busy, run: () => { yankTarget.value = v } },
      ]
    }
    if (canActivate(v)) {
      return [
        { key: 'activate', label: busy ? '...' : '设为激活', variant: 'primary', disabled: busy, run: () => handleActivate(v) },
      ]
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
    actions.push({ key: 'deprecate', label: '弃用', variant: 'ghost', disabled: busy, run: () => { deprecateTarget.value = v } })
  }
  return actions
}

// published 仅当前激活版本(is_active=true)称「已激活」；多个 published 候选不显示 lifecycle 徽标。
// 激活新版本后旧 active 版本 lifecycle_status 仍为 published，仅 is_active 翻 false ——
// 若一律标「已激活」会与按钮「设为激活」自相矛盾。
function lifecycleBadge(v: SkillVersion): { cls: string; label: string } | null {
  switch (v.lifecycle_status) {
    case 'published':
      return v.is_active ? { cls: 'bg-green-50 text-green-600', label: '已激活' } : null
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
      return { cls: 'bg-slate-100 text-slate-500', label: '待审核' }
  }
}

function driftBadge(v: SkillVersion): { cls: string; label: string; tip: string } | null {
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

async function handleActivate(v: SkillVersion): Promise<void> {
  actingId.value = v.id
  try {
    const skill = await activateSkillVersion(props.skillId, v.id)
    toast.success(`已激活版本 ${v.version}`)
    emit('activated', skill)
    await loadVersions(true)
  } catch (e) {
    toast.error((e as { message?: string }).message || '激活失败')
  } finally {
    actingId.value = null
  }
}

async function handleRestore(v: SkillVersion): Promise<void> {
  actingId.value = v.id
  try {
    const skill = await restoreSkillVersion(props.skillId, v.id)
    toast.success(`已恢复版本 ${v.version}`)
    emit('activated', skill)
    await loadVersions(true)
  } catch (e) {
    toast.error((e as { message?: string }).message || '恢复失败')
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
    await loadVersions(true)
  } catch (e) {
    toast.error((e as { message?: string }).message || '弃用失败')
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
    await loadVersions(true)
  } catch (e) {
    toast.error((e as { message?: string }).message || '撤回失败')
  } finally {
    actingId.value = null
  }
}

async function handleCheckDrift(v: SkillVersion): Promise<void> {
  checkingDriftId.value = v.id
  try {
    await checkSkillVersionDrift(props.skillId, v.id)
    toast.success('漂移检测完成')
    await loadVersions(true)
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
    const resynced = await resyncSkillVersion(props.skillId, target.id, resyncVersion.value.trim() || undefined)
    toast.success('已创建新版本，请完成安全审查后再激活')
    resyncTarget.value = null
    await loadVersions(false, resynced.id)
  } catch (e) {
    toast.error((e as { message?: string }).message || '重新同步失败')
  } finally {
    actingId.value = null
  }
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

function openCreate(): void {
  form.value = { version: '', version_label: '', change_log: '' }
  zipFile.value = null
  zipFileError.value = ''
  showCreate.value = true
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
    const created = await createSkillVersion(props.skillId, {
      version: form.value.version.trim(),
      version_label: form.value.version_label.trim(),
      change_log: form.value.change_log.trim(),
      zip_file: zipFile.value,
    })
    toast.success('版本创建成功（未激活，需通过安全审查后才可激活）')
    showCreate.value = false
    await loadVersions(false, created.id)
  } catch (e) {
    toast.error((e as { message?: string }).message || '创建失败')
  }
}

const createHint = computed(() => (zipFile.value ? `已选择：${zipFile.value.name}` : '不上传则沿用当前 active 内容作为新版本起点'))

const lifecycleBadgeSelected = computed(() =>
  selectedVersion.value ? lifecycleBadge(selectedVersion.value) : null,
)
const driftBadgeSelected = computed(() => (selectedVersion.value ? driftBadge(selectedVersion.value) : null))
const primarySelected = computed(() => (selectedVersion.value ? primaryActions(selectedVersion.value) : []))
const overflowSelected = computed(() => (selectedVersion.value ? overflowActions(selectedVersion.value) : []))
const tagsSelected = computed(() => (selectedVersion.value ? tagsForVersion(selectedVersion.value) : []))
const tagTargetTags = computed(() => (tagTarget.value ? tagsForVersion(tagTarget.value) : []))

// 供父组件在安全审查提交后触发重载（保持当前选中版本，不跳回 active）。
// withTags=false：审查/轮询不改 tags，跳过 tags 请求。
defineExpose({ reload: () => loadVersions(true, null, false) })
</script>

<template>
  <div class="flex flex-wrap items-center gap-1.5 border-b border-slate-200/60 bg-slate-50/40 px-4 py-2">
    <!-- 版本下拉 -->
    <div class="relative">
      <select
        class="rounded-md border border-slate-200 bg-white py-1 pl-2.5 pr-7 text-xs font-medium text-slate-800 focus:border-purple-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-400"
        :value="selectedVersion?.id"
        :disabled="loading || versions.length === 0"
        @change="onSelectChange"
      >
        <option v-for="v in versions" :key="v.id" :value="v.id">v{{ v.version }}</option>
      </select>
    </div>

    <!-- 状态徽标 -->
    <template v-if="selectedVersion">
      <span v-if="lifecycleBadgeSelected" class="rounded px-1.5 py-0.5 text-xs font-medium" :class="lifecycleBadgeSelected.cls">{{ lifecycleBadgeSelected.label }}</span>
      <span v-if="driftBadgeSelected" class="cursor-help rounded px-1.5 py-0.5 text-xs" :class="driftBadgeSelected.cls" :title="driftBadgeSelected.tip">{{ driftBadgeSelected.label }}</span>
      <span
        v-for="t in tagsSelected"
        :key="t.id"
        class="rounded px-1.5 py-0.5 text-xs"
        :class="t.is_system ? 'bg-slate-200 text-slate-500' : 'bg-purple-50 text-purple-600'"
      >{{ t.tag_name }}</span>
    </template>
    <span v-else-if="!loading" class="text-xs text-slate-400">暂无版本</span>

    <!-- 操作 -->
    <div class="ml-auto flex items-center gap-1">
      <template v-if="selectedVersion && (canManage || canActivate(selectedVersion))">
        <button
          v-for="a in primarySelected"
          :key="a.key"
          class="rounded px-1.5 py-0.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
          :class="variantClass(a.variant)"
          :disabled="a.disabled"
          :title="a.title"
          @click="a.run"
        >{{ a.label }}</button>
        <template v-if="overflowSelected.length">
          <div class="relative">
            <button class="rounded px-1 py-0.5 text-slate-500 hover:bg-slate-200" @click.stop="openMenu = !openMenu">
              <MoreVertical class="h-3.5 w-3.5" />
            </button>
            <div
              v-if="openMenu"
              class="absolute right-0 top-full z-20 mt-1 min-w-[8rem] rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
            >
              <button
                v-for="a in overflowSelected"
                :key="a.key"
                class="block w-full px-3 py-1.5 text-left text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
                :disabled="a.disabled"
                @click="openMenu = false; a.run()"
              >{{ a.label }}</button>
            </div>
            <div v-if="openMenu" class="fixed inset-0 z-10" @click="openMenu = false" />
          </div>
        </template>
      </template>

      <button
        v-if="canManage"
        class="flex items-center gap-1 rounded-md bg-purple-50 px-2 py-1 text-xs font-medium text-purple-600 transition-colors hover:bg-purple-100"
        @click="openCreate"
      >
        <Plus class="h-3 w-3" /> 新版本
      </button>
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

    <!-- 新版本 -->
    <div v-if="showCreate" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
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

    <!-- 重新同步 -->
    <div v-if="resyncTarget" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-2 text-lg font-semibold text-slate-900">重新同步漂移版本</h3>
        <p class="mb-3 text-sm text-slate-500">
          将重新拉取版本 <span class="font-mono">v{{ resyncTarget.version }}</span> 的源内容并作为新版本入库。新版本需通过安全审查后才能激活。
        </p>
        <div class="mb-4">
          <label class="mb-1 block text-xs font-medium text-slate-600">新版本号（留空自动 +patch）</label>
          <input v-model="resyncVersion" placeholder="如 1.0.1" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-amber-500 focus:outline-none" />
        </div>
        <div class="flex justify-end gap-3">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="resyncTarget = null">取消</button>
          <button
            class="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
            :disabled="actingId === resyncTarget.id"
            @click="confirmResync"
          >{{ actingId === resyncTarget.id ? '同步中…' : '确认重新同步' }}</button>
        </div>
      </div>
    </div>

    <!-- 版本别名 -->
    <div v-if="tagTarget" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-2 text-lg font-semibold text-slate-900">版本标签 · v{{ tagTarget.version }}</h3>
        <p class="mb-3 text-xs text-slate-500">
          标签指向具体版本（如 beta/stable），同名标签设置到新版本即移动。<span class="text-slate-400">latest 为系统保留，随最新已发布版本自动更新。</span>
        </p>
        <div v-if="tagTargetTags.length" class="mb-3 flex flex-wrap gap-1.5">
          <span
            v-for="t in tagTargetTags"
            :key="t.id"
            class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs"
            :class="t.is_system ? 'bg-slate-200 text-slate-500' : 'bg-purple-50 text-purple-600'"
          >
            {{ t.tag_name }}
            <button v-if="!t.is_system" class="text-purple-400 hover:text-purple-700" @click="handleRemoveTag(t.tag_name)">×</button>
          </span>
        </div>
        <div class="mb-4 flex gap-2">
          <input
            v-model="tagName"
            placeholder="如 beta / stable"
            class="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none"
            @keyup.enter="confirmSetTag"
          />
          <button class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700" @click="confirmSetTag">设置</button>
        </div>
        <div class="flex justify-end">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="tagTarget = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>
