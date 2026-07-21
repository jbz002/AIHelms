<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  createSkill,
  createSkillSecurityAudit,
  deleteSkill,
  getSkillById,
  getSkillCategories,
  getSkillDownloadUrl,
  toast,
  updateSkill,
  type Skill,
  type SkillCategory,
  type ProtocolIssue,
  usePermission,
} from '@aihelms/shared'
import { ArrowLeft, Download, FileText, PlayCircle, ShieldCheck, Trash2 } from 'lucide-vue-next'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import IconPicker from '../../components/IconPicker.vue'
import SkillVersionPanel from './SkillVersionPanel.vue'
import SkillContentPanel from './SkillContentPanel.vue'
import RatingOverviewPanel from '../../components/RatingOverviewPanel.vue'
import UsageStatsPanel from '../../components/UsageStatsPanel.vue'

type SecurityStatus = 'not_scanned' | 'queued' | 'running' | 'completed' | 'failed'
type SecurityDecision = 'passed' | 'attention_required' | 'high_risk' | 'failed'

interface SkillSecuritySummary {
  auditId: string
  status: SecurityStatus
  decision: SecurityDecision
  label: string
  score: number | null
  progress: number
  completedChecks: number
  totalChecks: number
  shortAdvice: string
}

const statusTone: Record<SecurityDecision | 'running' | 'not_scanned', string> = {
  passed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  attention_required: 'bg-amber-50 text-amber-700 ring-amber-200',
  high_risk: 'bg-red-50 text-red-700 ring-red-200',
  failed: 'bg-stone-100 text-stone-700 ring-stone-200',
  running: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
  not_scanned: 'bg-slate-100 text-slate-600 ring-slate-200',
}

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
const auditStarted = ref(false)
const zipFile = ref<File | null>(null)

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

const securitySummary = computed<SkillSecuritySummary | null>(() => {
  if (!skill.value) return null
  const s = skill.value
  const running = auditStarted.value || s.security_status === 'queued' || s.security_status === 'running'
  if (running) {
    return {
      auditId: s.latest_ai_policies_audit_code || '',
      status: 'running',
      decision: 'attention_required',
      label: '审查中',
      score: null,
      progress: 58,
      completedChecks: 3,
      totalChecks: 5,
      shortAdvice: '正在检查 Skill 压缩包内容，完成后自动生成报告。',
    }
  }
  if (s.security_status === 'failed' || s.security_decision === 'failed') {
    return {
      auditId: s.latest_ai_policies_audit_code || '',
      status: 'failed',
      decision: 'failed',
      label: '审查失败',
      score: null,
      progress: 100,
      completedChecks: 0,
      totalChecks: 5,
      shortAdvice: '审查执行失败，请重新发起或检查 zip 文件。',
    }
  }
  if (s.security_status !== 'completed') {
    return {
      auditId: '',
      status: 'not_scanned',
      decision: 'passed',
      label: '未审查',
      score: null,
      progress: 0,
      completedChecks: 0,
      totalChecks: 5,
      shortAdvice: 'zip 已上传，点击审查后生成独立审查任务。',
    }
  }
  return {
    auditId: s.latest_ai_policies_audit_code || '',
    status: 'completed',
    decision: (s.security_decision || 'passed') as SecurityDecision,
    label: s.security_decision === 'high_risk' ? '高风险' : s.security_decision === 'attention_required' ? '建议修改' : '通过',
    score: s.security_risk_score ?? 0,
    progress: 100,
    completedChecks: 5,
    totalChecks: 5,
    shortAdvice:
      s.security_decision === 'high_risk'
        ? '发现高优先级风险，建议发布前复核。'
        : s.security_decision === 'attention_required'
          ? '存在需要关注的风险点，建议按报告处理。'
          : '未发现明显高优先级风险。',
  }
})

async function loadData(): Promise<void> {
  loading.value = true
  try {
    const cats = await getSkillCategories()
    categories.value = cats
    if (!isNew.value && skillId.value) {
      const s = await getSkillById(skillId.value)
      skill.value = s
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

function handleZipChange(event: Event): void {
  const target = event.target as HTMLInputElement
  zipFile.value = target.files?.[0] || null
}

function handleVersionActivated(updated: Skill): void {
  skill.value = updated
}

async function handleSave(): Promise<void> {
  if (!form.value.name.trim()) {
    toast.error('请填写名称')
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
      version: form.value.version,
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

function openAiPolicies(): void {
  if (!skill.value || !securitySummary.value) return
  if (!securitySummary.value.auditId) {
    toast.error('暂无可查看的审查报告')
    return
  }
  router.push(`/ai-policies/audits/${securitySummary.value.auditId}?skill_id=${skill.value.id}`)
}

async function startSecurityAudit(): Promise<void> {
  if (!skill.value?.has_zip) {
    toast.error('请先上传 Skill zip 包')
    return
  }
  try {
    auditStarted.value = true
    const audit = await createSkillSecurityAudit(skill.value.id)
    skill.value = {
      ...skill.value,
      security_status: audit.status,
      security_decision: audit.decision,
      security_severity: audit.severity,
      security_risk_score: audit.risk_score,
      latest_ai_policies_audit_code: audit.audit_id,
    }
    toast.success('已提交审查，可在 AI Policies 查看进度')
  } catch (e) {
    auditStarted.value = false
    toast.error((e as { message?: string }).message || '审查任务创建失败')
  }
}

function securityBadgeClass(): string {
  if (!securitySummary.value) return statusTone.not_scanned
  if (securitySummary.value.status === 'running' || securitySummary.value.status === 'queued') return statusTone.running
  if (securitySummary.value.status === 'not_scanned') return statusTone.not_scanned
  return statusTone[securitySummary.value.decision]
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
              v-model="form.version"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div class="col-span-2">
            <label class="mb-1 block text-sm font-medium text-slate-700">标签（逗号分隔）</label>
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

          <div v-if="!isNew && skill?.has_zip && securitySummary" class="col-span-2 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <ShieldCheck class="h-4 w-4 text-purple-600" />
                  <h2 class="text-sm font-semibold text-slate-900">AI Policies 最近审查</h2>
                  <span class="rounded-full px-2 py-0.5 text-[11px] font-medium ring-1" :class="securityBadgeClass()">
                    {{ securitySummary.label }}
                  </span>
                </div>
                <p class="mt-1 text-sm text-slate-500">{{ securitySummary.shortAdvice }}</p>
              </div>
              <div class="flex gap-2">
                <button
                  class="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-purple-300 hover:text-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="securitySummary.status === 'running'"
                  @click="startSecurityAudit"
                >
                  <PlayCircle class="h-3.5 w-3.5" />
                  {{ securitySummary.status === 'running' || securitySummary.status === 'queued' ? '审查中' : securitySummary.status === 'not_scanned' ? '安全审查' : '重新审查' }}
                </button>
                <button
                  v-if="securitySummary.status !== 'not_scanned'"
                  class="inline-flex items-center gap-1 rounded-lg bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-500"
                  @click="openAiPolicies"
                >
                  <FileText class="h-3.5 w-3.5" />
                  {{ securitySummary.status === 'running' ? '查看进度' : '查看报告' }}
                </button>
              </div>
            </div>
            <div v-if="securitySummary.status !== 'not_scanned'" class="mt-4 flex items-center gap-3">
              <div class="h-2 flex-1 overflow-hidden rounded-full bg-slate-200">
                <div
                  class="h-full rounded-full"
                  :class="securitySummary.status === 'running' ? 'bg-indigo-500' : securitySummary.decision === 'high_risk' ? 'bg-red-500' : 'bg-purple-500'"
                  :style="{ width: `${securitySummary.progress}%` }"
                />
              </div>
              <div class="w-28 text-right text-xs text-slate-500">
                {{ securitySummary.completedChecks }}/{{ securitySummary.totalChecks }} 项 · {{ securitySummary.progress }}%
              </div>
            </div>
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
