<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  createSkill,
  deleteSkill,
  getSkillById,
  getSkillCategories,
  getSkillDownloadUrl,
  setSkillHidden,
  listLabelDefinitions,
  grantSkillLabel,
  revokeSkillLabel,
  listSkillLabels,
  toast,
  updateSkill,
  LabelBadge,
  type Skill,
  type SkillCategory,
  type LabelDefinition,
  type SkillLabelGrant,
  type ProtocolIssue,
  usePermission,
} from '@aihelms/shared'
import { ArrowLeft, Download, Trash2, Award, Lock } from 'lucide-vue-next'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import IconPicker from '../../components/IconPicker.vue'
import SkillVersionPanel from './SkillVersionPanel.vue'
import SkillContentPanel from './SkillContentPanel.vue'
import RatingOverviewPanel from '../../components/RatingOverviewPanel.vue'
import UsageStatsPanel from '../../components/UsageStatsPanel.vue'

const { hasPermission } = usePermission()
const route = useRoute()
const router = useRouter()

const isNew = computed(() => route.params.id === 'new')
const skillId = computed(() => (isNew.value ? null : Number(route.params.id)))

const skill = ref<Skill | null>(null)
const categories = ref<SkillCategory[]>([])
const loading = ref(false)
const saving = ref(false)
const showDelete = ref(false)
const zipFile = ref<File | null>(null)
const zipFileError = ref('')

// 镜像服务端 SKILLS_PACKAGE_MAX_TOTAL_SIZE_MB 默认值；服务端为准
const MAX_ZIP_SIZE = 100 * 1024 * 1024

const form = ref({
  name: '',
  icon: '📦',
  description: '',
  author: '',
  category: 'general',
  version: '1.0.0',
  tags: '',
  usage_instructions: '',
  is_published: false,
  requires_approval: false,
  visibility_type: 'all',
  source_url: '',
})
const sourceMode = ref<'zip' | 'url'>('zip')
const sourceUrlError = ref('')

const canManageLabel = hasPermission('skill:label:manage')
const labelDefs = ref<LabelDefinition[]>([])
const labels = ref<SkillLabelGrant[]>([])
const granting = ref(false)
const grantLabelName = ref('')
const grantNote = ref('')

const protocolBanner = computed<{
  cls: string
  title: string
  issues: ProtocolIssue[]
} | null>(() => {
  const v = skill.value?.active_version
  if (!v) return null
  const errs = (v.protocol_errors ?? []).filter((i) => i.severity === 'error')
  const warns = (v.protocol_errors ?? []).filter((i) => i.severity === 'warning')
  if (errs.length) {
    return {
      cls: 'border-red-200 bg-red-50 text-red-700',
      title: 'SKILL.md 协议校验未通过：该版本不可激活/发布，请修正后重传 zip',
      issues: errs,
    }
  }
  if (warns.length) {
    return {
      cls: 'border-amber-200 bg-amber-50 text-amber-700',
      title: 'SKILL.md 协议告警（不阻断，建议修正）',
      issues: warns,
    }
  }
  return null
})

async function loadData(): Promise<void> {
  loading.value = true
  try {
    const cats = await getSkillCategories()
    categories.value = cats
    if (!isNew.value && skillId.value) {
      const s = await getSkillById(skillId.value)
      skill.value = s
      labels.value = s.labels ?? []
      if (canManageLabel) {
        labelDefs.value = await listLabelDefinitions(true).catch(() => [])
      }
      form.value = {
        name: s.name,
        icon: s.icon,
        description: s.description,
        author: s.author ?? '',
        category: s.category,
        version: s.version,
        tags: (s.tags || []).join(', '),
        usage_instructions: s.usage_instructions,
        is_published: s.is_published,
        requires_approval: s.requires_approval,
        visibility_type: s.visibility_type || 'all',
        source_url: '',
      }
    } else {
      form.value.category = cats[0]?.name || 'general'
    }
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function handleGrantLabel(): Promise<void> {
  if (!skillId.value || !grantLabelName.value) return
  granting.value = true
  try {
    await grantSkillLabel(skillId.value, grantLabelName.value, grantNote.value.trim())
    toast.success('治理标签已授予')
    grantLabelName.value = ''
    grantNote.value = ''
    labels.value = await listSkillLabels(skillId.value)
  } catch (e) {
    toast.error((e as { message?: string }).message || '授予失败')
  } finally {
    granting.value = false
  }
}

async function handleRevokeLabel(name: string): Promise<void> {
  if (!skillId.value) return
  try {
    await revokeSkillLabel(skillId.value, name)
    toast.success('治理标签已撤销')
    labels.value = await listSkillLabels(skillId.value)
  } catch (e) {
    toast.error((e as { message?: string }).message || '撤销失败')
  }
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

function handleVersionActivated(updated: Skill): void {
  skill.value = updated
}

async function handleToggleHidden(): Promise<void> {
  if (!skill.value) return
  const next = !skill.value.hidden
  try {
    const updated = await setSkillHidden(skill.value.id, next)
    skill.value = updated
    toast.success(next ? '已治理下架' : '已恢复上架')
  } catch (e) {
    toast.error((e as { message?: string }).message || '操作失败')
  }
}

async function handleSave(): Promise<void> {
  if (!form.value.name.trim()) {
    toast.error('请填写名称')
    return
  }
  if (zipFileError.value) {
    toast.error(zipFileError.value)
    return
  }
  saving.value = true
  try {
    const tags = form.value.tags
      ? form.value.tags.split(',').map((t) => t.trim()).filter(Boolean)
      : []
    const payload = {
      name: form.value.name.trim(),
      icon: form.value.icon,
      description: form.value.description,
      author: form.value.author,
      category: form.value.category,
      version: isNew.value ? form.value.version : undefined,
      tags,
      usage_instructions: form.value.usage_instructions,
      is_published: form.value.is_published,
      requires_approval: form.value.requires_approval,
      visibility_type: form.value.visibility_type,
      zip_file: sourceMode.value === 'zip' ? zipFile.value : undefined,
      source_url: sourceMode.value === 'url' ? form.value.source_url : undefined,
    }
    if (isNew.value) {
      await createSkill(payload)
      toast.success('Skill 创建成功')
      router.push('/skills')
    } else if (skillId.value) {
      await updateSkill(skillId.value, payload)
      toast.success('Skill 更新成功')
      router.push('/skills')
    }
  } catch (e) {
    toast.error((e as { message?: string }).message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleDelete(): Promise<void> {
  if (!skillId.value) return
  try {
    await deleteSkill(skillId.value)
    toast.success('Skill 删除成功')
    router.push('/skills')
  } catch (e) {
    toast.error((e as { message?: string }).message || '删除失败')
  }
}

function downloadZip(): void {
  if (!skill.value?.has_zip) return
  const url = getSkillDownloadUrl(skill.value.id)
  const token = localStorage.getItem('aihelms_token')
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then((res) => res.blob())
    .then((blob) => {
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = skill.value!.zip_filename || `${skill.value!.name}.zip`
      link.click()
      URL.revokeObjectURL(link.href)
    })
    .then(() => loadData())
}

onMounted(loadData)
</script>

<template>
  <div>
    <div class="mb-6 flex items-center justify-between">
      <button
        class="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
        @click="router.push('/skills')"
      >
        <ArrowLeft class="h-4 w-4" />
        返回列表
      </button>
      <button
        v-if="!isNew && hasPermission('skill:delete')"
        class="flex items-center gap-1 rounded-lg bg-red-50 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-100"
        @click="showDelete = true"
      >
        <Trash2 class="h-4 w-4" />
        删除
      </button>
    </div>

    <div v-if="loading" class="py-20 text-center text-sm text-slate-400">加载中...</div>
    <template v-else>
      <div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 class="mb-5 text-xl font-bold text-slate-900">
          {{ isNew ? '新建 Skill' : `编辑：${form.name || ''}` }}
        </h1>

        <div
          v-if="protocolBanner"
          class="mb-4 rounded-lg border px-4 py-3 text-sm"
          :class="protocolBanner.cls"
        >
          <div class="font-medium">{{ protocolBanner.title }}</div>
          <ul class="mt-1 list-disc space-y-0.5 pl-5">
            <li v-for="(issue, idx) in protocolBanner.issues" :key="idx">{{ issue.message }}</li>
          </ul>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">名称 *</label>
            <input
              v-model="form.name"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div>
            <IconPicker v-model="form.icon" label="图标" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">作者</label>
            <input
              v-model="form.author"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">分类</label>
            <select
              v-model="form.category"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            >
              <option v-for="c in categories" :key="c.id" :value="c.name">{{ c.name }}</option>
            </select>
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">版本</label>
            <input
              v-if="isNew"
              v-model="form.version"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
            <div
              v-else
              class="flex h-[38px] items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3"
            >
              <span class="inline-flex items-center rounded bg-purple-50 px-1.5 py-0.5 font-mono text-xs font-medium text-purple-600">v{{ form.version }}</span>
              <Lock class="h-3.5 w-3.5 shrink-0 text-slate-400" />
              <span class="truncate text-xs text-slate-400">由下方「版本管理」新增/激活，此处仅展示</span>
            </div>
          </div>
          <div class="col-span-2">
            <label class="mb-1 block text-sm font-medium text-slate-700">分类关键词（逗号分隔）</label>
            <input
              v-model="form.tags"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
              placeholder="legal, ocr, markdown"
            />
          </div>
          <div class="col-span-2">
            <label class="mb-1 block text-sm font-medium text-slate-700">描述</label>
            <textarea
              v-model="form.description"
              rows="2"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div class="col-span-2">
            <label class="mb-1 block text-sm font-medium text-slate-700">使用说明（支持 Markdown）</label>
            <textarea
              v-model="form.usage_instructions"
              rows="8"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div class="col-span-2">
            <label v-if="isNew" class="mb-1 block text-sm font-medium text-slate-700">来源方式</label>
            <div v-if="isNew" class="mb-2 flex gap-2">
              <button
                type="button"
                :class="sourceMode === 'zip' ? 'rounded-lg bg-purple-600 px-3 py-1.5 text-xs font-medium text-white' : 'rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200'"
                @click="sourceMode = 'zip'"
              >
                上传 zip 包
              </button>
              <button
                type="button"
                :class="sourceMode === 'url' ? 'rounded-lg bg-purple-600 px-3 py-1.5 text-xs font-medium text-white' : 'rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200'"
                @click="sourceMode = 'url'"
              >
                仓库 URL
              </button>
            </div>
            <label class="mb-1 block text-sm font-medium text-slate-700">
              <span v-if="isNew">上传 zip 包</span>
              <span v-else>当前 active 文件</span>
            </label>
            <div class="flex items-center gap-3">
              <input
                v-if="isNew"
                type="file"
                accept=".zip"
                class="block flex-1 text-sm text-slate-700 file:mr-3 file:rounded-md file:border-0 file:bg-purple-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-purple-700 hover:file:bg-purple-100"
                @change="handleZipChange"
              />
              <span v-else-if="skill?.zip_filename" class="flex-1 text-xs text-slate-600">
                {{ skill.zip_filename }} ({{ Math.round((skill.zip_size || 0) / 1024) }} KB)
                · 已下载 {{ skill?.install_count }} 次
              </span>
              <span v-else class="flex-1 text-xs text-slate-400">暂无文件</span>
              <button
                v-if="!isNew && skill?.has_zip"
                class="flex items-center gap-1 rounded-md bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200"
                @click="downloadZip"
              >
                <Download class="h-3 w-3" />
                下载当前
              </button>
            </div>
            <div v-if="isNew && zipFile" class="mt-1 text-xs text-slate-500">
              已选择：{{ zipFile.name }} ({{ Math.round(zipFile.size / 1024) }} KB)
            </div>
            <p v-if="isNew && zipFileError" class="mt-1 text-xs text-red-500">
              {{ zipFileError }}
            </p>
            <p v-if="isNew && sourceMode === 'zip'" class="mt-1 text-xs text-slate-400">
              允许的文件类型：md/json/txt/py/js/sh/yaml/csv/png/jpg/svg/pdf 等；单文件 ≤10MB，总包 ≤100MB，最多 500 文件
            </p>
            <div v-if="isNew && sourceMode === 'url'" class="mt-2">
              <input
                v-model="form.source_url"
                class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
                placeholder="https://github.com/owner/repo/tree/main"
                @input="sourceUrlError = ''"
              />
              <p v-if="sourceUrlError" class="mt-1 text-xs text-red-500">{{ sourceUrlError }}</p>
              <p class="mt-1 text-[11px] text-slate-400">
                支持的仓库：GitHub、Gitee、GitLab（需管理员配置白名单域名）
              </p>
            </div>
            <p v-if="!isNew" class="mt-1 text-[11px] text-slate-400">
              内容变更请在下方「版本管理」中创建新版本并通过安全审查后激活。
            </p>
          </div>

          <div v-if="!isNew && skillId" class="col-span-2">
            <SkillVersionPanel
              :skill-id="skillId"
              :active-version="skill?.active_version ?? null"
              @activated="handleVersionActivated"
            />
          </div>

          <div v-if="!isNew && skillId" class="col-span-2">
            <SkillContentPanel :skill-id="skillId" />
          </div>

          <div v-if="!isNew && skillId" class="col-span-2">
            <h3 class="mb-3 text-sm font-semibold text-slate-900">评分概览</h3>
            <RatingOverviewPanel entity-type="skill" :entity-id="skillId" />
          </div>

          <div v-if="!isNew && skillId" class="col-span-2">
            <h3 class="mb-3 text-sm font-semibold text-slate-900">使用统计</h3>
            <UsageStatsPanel entity-type="skill" :entity-id="skillId" />
          </div>

          <div class="col-span-2">
            <label class="mb-1 block text-sm font-medium text-slate-700">可见性</label>
            <select
              v-model="form.visibility_type"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            >
              <option value="all">公开（进入市场列表）</option>
              <option value="private">仅创建者（私有）</option>
              <option value="unlisted">不列出（仅直链可访问）</option>
            </select>
            <p class="mt-1 text-xs text-slate-400">
              private 仅创建者和管理员可见；unlisted 不进市场列表，持有直链的登录用户可查看详情
            </p>
          </div>
          <div class="col-span-2 flex items-center gap-4">
            <label class="flex items-center gap-2 text-sm text-slate-700">
              <input v-model="form.is_published" type="checkbox" class="h-4 w-4 rounded border-slate-300" />
              发布到用户端
            </label>
            <label class="flex items-center gap-2 text-sm text-slate-700">
              <input
                v-model="form.requires_approval"
                type="checkbox"
                :disabled="!form.is_published"
                class="h-4 w-4 rounded border-slate-300 disabled:opacity-50"
              />
              领用前需要审批
            </label>
          </div>
          <div v-if="skill" class="col-span-2 flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2">
            <div>
              <p class="text-sm font-medium text-slate-700">治理下架（hidden）</p>
              <p class="text-xs text-slate-400">独立的治理下架 overlay，与发布开关、可见性正交。下架后非管理员不可见。</p>
            </div>
            <div class="flex items-center gap-2">
              <span
                v-if="skill.hidden"
                class="rounded bg-red-50 px-1.5 py-0.5 text-[10px] text-red-600"
              >已下架</span>
              <button
                class="rounded-md px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50"
                :class="skill.hidden ? 'bg-slate-200 text-slate-600 hover:bg-slate-300' : 'bg-red-50 text-red-600 hover:bg-red-100'"
                @click="handleToggleHidden"
              >
                {{ skill.hidden ? '恢复上架' : '下架' }}
              </button>
            </div>
          </div>
          <div v-if="skill" class="col-span-2 rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2">
            <div class="mb-2 flex items-center gap-1.5">
              <Award class="h-4 w-4 text-amber-500" />
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

        <div class="mt-6 flex justify-end gap-3 border-t border-slate-100 pt-4">
          <button
            class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
            @click="router.push('/skills')"
          >
            取消
          </button>
          <button
            class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            :disabled="saving"
            @click="handleSave"
          >
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </template>

    <ConfirmDialog
      :visible="showDelete"
      title="删除 Skill"
      :message="`确认删除 ${skill?.name}？此操作不可恢复，包含的 zip 文件也会被删除。`"
      @confirm="handleDelete"
      @cancel="showDelete = false"
    />
  </div>
</template>
