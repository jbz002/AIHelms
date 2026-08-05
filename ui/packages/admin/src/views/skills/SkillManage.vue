<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  createSkillCategory,
  deleteSkill,
  deleteSkillCategory,
  getSkillCategories,
  getSkillDownloadUrl,
  getSkills,
  toast,
  type Skill,
  type SkillCategory,
  type SkillVersion,
  type ProtocolIssue,
  usePermission,
} from '@aihelms/shared'
import { BarChart3, Download, Search, X } from 'lucide-vue-next'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import HostedIcon from '@aihelms/shared/src/components/HostedIcon.vue'
import SkillForm from './SkillForm.vue'
import SkillGovernancePanel from './SkillGovernancePanel.vue'
import SkillVersionSwitcher from './SkillVersionSwitcher.vue'
import SkillContentPanel from './SkillContentPanel.vue'
import UsageStatsPanel from '../../components/UsageStatsPanel.vue'

const { hasPermission } = usePermission()

const skills = ref<Skill[]>([])
const categories = ref<SkillCategory[]>([])
const loading = ref(false)
const selectedSkill = ref<Skill | null>(null)
const selectedSkillVersion = ref<SkillVersion | null>(null)

// 切换 Skill 时立即清空选中版本：SkillContentPanel 按选中 versionId 读内容，
// 旧 versionId 属于上一个 skill，后端归属校验会 404 → "加载摘要失败"。
// 清空后走 active 分支，待 SkillVersionSwitcher emit 正确 versionId 再带。
watch(
  () => selectedSkill.value?.id,
  () => {
    selectedSkillVersion.value = null
  },
)
const switcherRef = ref<InstanceType<typeof SkillVersionSwitcher> | null>(null)
const showForm = ref(false)
const editingSkill = ref<Skill | null>(null)
const deleteTarget = ref<Skill | null>(null)
const selectedCategory = ref<string | null>(null)
const skillQuery = ref('')
const showCategoryForm = ref(false)
const categoryFormName = ref('')
const categoryFormDescription = ref('')
const deleteCategoryTarget = ref<SkillCategory | null>(null)

const visibilityLabels: Record<string, string> = {
  all: '公开',
  private: '仅创建者',
  unlisted: '不列出',
}

const categoriesWithCount = computed(() => {
  const counts = new Map<string, number>()
  for (const s of skills.value) counts.set(s.category, (counts.get(s.category) || 0) + 1)
  return categories.value.map((c) => ({ ...c, count: counts.get(c.name) || 0 }))
})

const filteredSkills = computed(() => {
  const q = skillQuery.value.trim().toLowerCase()
  return skills.value.filter((s) => {
    const matchCat = !selectedCategory.value || s.category === selectedCategory.value
    const matchName = !q || s.name.toLowerCase().includes(q)
    return matchCat && matchName
  })
})

const protocolBanner = computed<{
  cls: string
  title: string
  issues: ProtocolIssue[]
} | null>(() => {
  const v = selectedSkillVersion.value
  if (!v) return null
  const errs = (v.protocol_errors ?? []).filter((i) => i.severity === 'error')
  const warns = (v.protocol_errors ?? []).filter((i) => i.severity === 'warning')
  if (errs.length) {
    return {
      cls: 'border-red-200 bg-red-50 text-red-700',
      title: 'SKILL.md 协议校验未通过：该版本不可激活，请修正后重传 zip',
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

function selectSkill(skill: Skill): void {
  // 必须同步清选中版本：selectedSkill 与 selectedSkillVersion 同一 tick 更新，
  // 否则 SkillContentPanel 的 prop-watch 会先用旧 versionId 查新 skill → 后端归属校验 404。
  selectedSkill.value = skill
  selectedSkillVersion.value = null
}

async function loadData(): Promise<void> {
  loading.value = true
  try {
    const [skillsRes, catsRes] = await Promise.all([getSkills(1, 200), getSkillCategories()])
    skills.value = skillsRes.items
    categories.value = catsRes
    if (selectedSkill.value) {
      const refreshed = skillsRes.items.find((s) => s.id === selectedSkill.value?.id)
      selectedSkill.value = refreshed || null
    } else if (skillsRes.items.length > 0) {
      selectedSkill.value = skillsRes.items[0]
    }
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editingSkill.value = null
  showForm.value = true
}

function openEdit(): void {
  if (!selectedSkill.value) return
  editingSkill.value = selectedSkill.value
  showForm.value = true
}

async function handleSaved(): Promise<void> {
  showForm.value = false
  await loadData()
}

function handleVersionActivated(updated: Skill): void {
  const idx = skills.value.findIndex((s) => s.id === updated.id)
  if (idx >= 0) skills.value[idx] = updated
  if (selectedSkill.value?.id === updated.id) selectedSkill.value = updated
}

async function confirmDelete(): Promise<void> {
  if (!deleteTarget.value) return
  try {
    await deleteSkill(deleteTarget.value.id)
    toast.success('Skill 删除成功')
    if (selectedSkill.value?.id === deleteTarget.value.id) selectedSkill.value = null
    deleteTarget.value = null
    await loadData()
  } catch (e) {
    toast.error((e as { message?: string }).message || '删除失败')
  }
}

function downloadZip(): void {
  const skill = selectedSkill.value
  const version = selectedSkillVersion.value
  if (!skill || !version?.zip_filename) return
  const url = getSkillDownloadUrl(skill.id, version.id)
  const token = localStorage.getItem('aihelms_token')
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then((res) => res.blob())
    .then((blob) => {
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = version.zip_filename || `${skill.name}.zip`
      link.click()
      URL.revokeObjectURL(link.href)
    })
    .then(() => loadData())
}

async function handleCreateCategory(): Promise<void> {
  if (!categoryFormName.value.trim()) {
    toast.error('请输入分类名称')
    return
  }
  try {
    await createSkillCategory({
      name: categoryFormName.value.trim(),
      description: categoryFormDescription.value.trim(),
    })
    toast.success('分类创建成功')
    showCategoryForm.value = false
    categoryFormName.value = ''
    categoryFormDescription.value = ''
    await loadData()
  } catch (e) {
    toast.error((e as { message?: string }).message || '创建失败')
  }
}

async function confirmDeleteCategory(): Promise<void> {
  if (!deleteCategoryTarget.value) return
  try {
    await deleteSkillCategory(deleteCategoryTarget.value.id)
    toast.success('分类删除成功')
    if (selectedCategory.value === deleteCategoryTarget.value.name) selectedCategory.value = null
    deleteCategoryTarget.value = null
    await loadData()
  } catch (e) {
    toast.error((e as { message?: string }).message || '删除失败')
  }
}

onMounted(loadData)

// 安全审查异步跑在 celery，提交后 status=queued/running，扫描完成才落 DB。
// 轮询版本状态直到终态，避免用户手动刷新页面才看到结果。
let auditPollTimer: ReturnType<typeof setInterval> | null = null
let auditPollCount = 0
const AUDIT_POLL_INTERVAL = 4000
const AUDIT_POLL_MAX = 75 // 75 * 4s = 5min 兜底

function stopAuditPolling(): void {
  if (auditPollTimer) {
    clearInterval(auditPollTimer)
    auditPollTimer = null
  }
  auditPollCount = 0
}

watch(
  () => selectedSkillVersion.value?.security_status,
  (status, prev) => {
    // 终态到达：给一次完成/失败提示
    if (prev && (prev === 'queued' || prev === 'running')) {
      if (status === 'completed') {
        const decision = selectedSkillVersion.value?.security_decision
        const label =
          decision === 'passed'
            ? '审查通过'
            : decision === 'attention_required'
              ? '建议修改'
              : decision === 'high_risk'
                ? '高风险'
                : '已完成'
        toast.success(`安全审查完成：${label}`)
      } else if (status === 'failed') {
        toast.error('安全审查失败，请查看报告或重试')
      }
    }
    // 进入审查中 → 启动轮询；否则停止
    stopAuditPolling()
    if (status === 'queued' || status === 'running') {
      auditPollCount = 0
      auditPollTimer = setInterval(async () => {
        auditPollCount++
        if (auditPollCount > AUDIT_POLL_MAX) {
          stopAuditPolling()
          return
        }
        await switcherRef.value?.reload()
      }, AUDIT_POLL_INTERVAL)
    }
  },
)

onUnmounted(stopAuditPolling)
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="flex flex-1 gap-4 overflow-hidden">
      <!-- 左侧：分类导航 + Skill 列表 -->
      <div class="w-80 shrink-0 overflow-hidden rounded-2xl border border-slate-200/60 bg-white shadow-sm">
        <div class="flex h-12 items-center justify-between border-b border-slate-200/60 px-4">
          <h3 class="text-sm font-semibold text-slate-900">Skill</h3>
          <button
            v-if="hasPermission('skill:create')"
            class="rounded-md bg-purple-600 px-2.5 py-1 text-xs font-medium text-white transition-all hover:bg-purple-500"
            @click="openCreate"
          >
            新建
          </button>
        </div>

        <!-- 分类导航 -->
        <div class="border-b border-slate-100 px-2 py-1.5">
          <div class="mb-1 flex items-center justify-between px-1">
            <span class="text-xs font-medium text-slate-400">分类</span>
            <button
              v-if="hasPermission('skill:create')"
              class="text-xs text-purple-500 transition-colors hover:text-purple-600"
              @click="showCategoryForm = true"
            >
              +新建
            </button>
          </div>
          <button
            class="mb-0.5 w-full rounded-md px-3 py-1.5 text-left text-xs font-medium transition-colors"
            :class="!selectedCategory ? 'bg-purple-50 text-purple-700' : 'text-slate-500 hover:bg-slate-50'"
            @click="selectedCategory = null"
          >
            全部 ({{ skills.length }})
          </button>
          <div
            v-for="cat in categoriesWithCount"
            :key="cat.id"
            class="group mb-0.5 flex items-center justify-between rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
            :class="selectedCategory === cat.name ? 'bg-purple-50 text-purple-700' : 'text-slate-500 hover:bg-slate-50'"
          >
            <button class="flex-1 text-left" @click="selectedCategory = cat.name">
              {{ cat.name }} ({{ cat.count }})
            </button>
            <button
              v-if="hasPermission('skill:delete')"
              class="hidden text-red-400 hover:text-red-600 group-hover:block"
              @click="deleteCategoryTarget = cat"
            >
              ×
            </button>
          </div>
        </div>

        <!-- 搜索 + Skill 列表 -->
        <div class="overflow-y-auto p-2" style="max-height: calc(100vh - 14rem)">
          <div class="relative mb-2 px-0.5">
            <Search class="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
            <input
              v-model="skillQuery"
              class="w-full rounded-md border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-xs text-slate-700 focus:border-purple-500 focus:outline-none"
              placeholder="搜索 Skill 名称"
            />
          </div>
          <div v-if="loading" class="py-8 text-center text-sm text-slate-400">加载中...</div>
          <div v-else-if="filteredSkills.length === 0" class="py-8 text-center text-sm text-slate-400">
            暂无 Skill
          </div>
          <div
            v-for="skill in filteredSkills"
            :key="skill.id"
            class="mb-1 flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 transition-colors"
            :class="selectedSkill?.id === skill.id ? 'bg-purple-50 ring-1 ring-purple-200' : 'hover:bg-slate-50'"
            @click="selectSkill(skill)"
          >
            <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100">
              <HostedIcon :src="skill.icon_url" :size="18" :alt="skill.name" />
            </div>
            <div class="min-w-0 flex-1">
              <span
                class="block truncate text-sm font-medium"
                :class="selectedSkill?.id === skill.id ? 'text-purple-700' : 'text-slate-900'"
              >
                {{ skill.name }}
              </span>
              <div class="mt-0.5 flex items-center gap-1.5">
                <span class="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">v{{ skill.version }}</span>
                <span v-if="skill.is_published" class="rounded bg-green-50 px-1 py-0.5 text-[10px] text-green-600">已发布</span>
                <span v-if="skill.requires_approval" class="rounded bg-amber-50 px-1 py-0.5 text-[10px] text-amber-600">需审批</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：只读详情 + 子面板 -->
      <div class="flex-1 overflow-hidden rounded-2xl border border-slate-200/60 bg-white shadow-sm">
        <template v-if="selectedSkill">
          <div class="flex h-12 items-center justify-between border-b border-slate-200/60 px-4">
            <div class="flex items-center gap-2">
              <h3 class="text-sm font-semibold text-slate-900">{{ selectedSkill.name }}</h3>
              <span v-if="selectedSkill.hidden" class="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-600">已下架</span>
            </div>
            <div class="flex gap-1.5">
              <button
                v-if="hasPermission('skill:update')"
                class="rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200"
                @click="openEdit"
              >
                编辑
              </button>
              <button
                v-if="hasPermission('skill:delete')"
                class="rounded-md bg-red-50 px-2.5 py-1 text-xs font-medium text-red-600 transition-colors hover:bg-red-100"
                @click="deleteTarget = selectedSkill"
              >
                删除
              </button>
            </div>
          </div>

          <SkillVersionSwitcher
            ref="switcherRef"
            :skill-id="selectedSkill.id"
            :active-version="selectedSkill.active_version ?? null"
            @select="selectedSkillVersion = $event"
            @activated="handleVersionActivated"
          />

          <div class="overflow-y-auto p-4" style="max-height: calc(100vh - 10rem)">
            <!-- 协议校验提示 -->
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

            <!-- 基本信息（本体 + 当前版本） -->
            <div class="mb-4 rounded-xl border border-slate-200/60 p-3">
              <h4 class="mb-3 text-sm font-semibold text-slate-900">基本信息</h4>
              <div class="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                <div>
                  <span class="text-slate-500">作者：</span>
                  <span class="text-slate-700">{{ selectedSkill.author || '-' }}</span>
                </div>
                <div>
                  <span class="text-slate-500">分类：</span>
                  <span class="text-slate-700">{{ selectedSkill.category }}</span>
                </div>
                <div>
                  <span class="text-slate-500">分类关键词：</span>
                  <span class="text-slate-700">{{ selectedSkill.tags?.length ? selectedSkill.tags.join(', ') : '-' }}</span>
                </div>
                <div>
                  <span class="text-slate-500">可见性：</span>
                  <span class="text-slate-700">{{ visibilityLabels[selectedSkill.visibility_type || 'all'] }}</span>
                </div>
                <div>
                  <span class="text-slate-500">发布：</span>
                  <span class="text-slate-700">{{ selectedSkill.is_published ? '已发布' : '未发布' }}</span>
                </div>
                <div>
                  <span class="text-slate-500">领用方式：</span>
                  <span class="text-slate-700">{{ selectedSkill.requires_approval ? '需审批' : '直接领用' }}</span>
                </div>
                <template v-if="selectedSkillVersion">
                  <div>
                    <span class="text-slate-500">来源：</span>
                    <span class="text-slate-700">{{ selectedSkillVersion.source_type === 'url' ? 'URL 同步' : '手动上传' }}</span>
                  </div>
                  <div>
                    <span class="text-slate-500">协议：</span>
                    <span class="text-slate-700">{{ selectedSkillVersion.protocol_valid ? '合规' : '不合规' }}</span>
                  </div>
                  <div class="col-span-2">
                    <span class="text-slate-500">文件：</span>
                    <span v-if="selectedSkillVersion.zip_filename" class="text-slate-700">
                      {{ selectedSkillVersion.zip_filename }} ({{ Math.round((selectedSkillVersion.zip_size || 0) / 1024) }} KB)
                    </span>
                    <span v-else class="text-slate-400">无独立 zip</span>
                    <button
                      v-if="selectedSkillVersion.zip_filename"
                      class="ml-2 inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-slate-200"
                      @click="downloadZip"
                    >
                      <Download class="h-3 w-3" />
                      下载
                    </button>
                  </div>
                </template>

                <div v-if="selectedSkill.description" class="col-span-2">
                  <span class="text-slate-500">描述：</span>
                  <span class="text-slate-700">{{ selectedSkill.description }}</span>
                </div>
                <div v-if="selectedSkill.usage_instructions" class="col-span-2">
                  <span class="text-slate-500">使用说明：</span>
                  <span class="whitespace-pre-wrap text-slate-700">{{ selectedSkill.usage_instructions }}</span>
                </div>
                <div v-if="selectedSkillVersion?.change_log" class="col-span-2">
                  <span class="text-slate-500">变更说明：</span>
                  <span class="whitespace-pre-wrap text-slate-700">{{ selectedSkillVersion.change_log }}</span>
                </div>
              </div>
            </div>

            <!-- 内容：概览/摘要 + 完整指令/内容完整性/安全审查 抽屉 -->
            <SkillContentPanel
              :skill-id="selectedSkill.id"
              :version="selectedSkillVersion"
              @audited="switcherRef?.reload()"
            />

            <!-- 治理 -->
            <SkillGovernancePanel :skill="selectedSkill" @changed="loadData" />

            <!-- 使用统计 -->
            <div class="mb-4 rounded-xl border border-slate-200/60 p-3">
              <h4 class="mb-3 flex items-center gap-1.5 text-sm font-semibold text-slate-900">
                <BarChart3 class="h-4 w-4 text-purple-500" /> 使用统计
              </h4>
              <UsageStatsPanel entity-type="skill" :entity-id="selectedSkill.id" />
            </div>
          </div>
        </template>
        <template v-else>
          <div class="flex h-full items-center justify-center text-sm text-slate-400">
            请从左侧选择 Skill 查看详情
          </div>
        </template>
      </div>
    </div>

    <!-- Skill form dialog -->
    <SkillForm
      :visible="showForm"
      :editing="editingSkill"
      :categories="categories"
      @close="showForm = false"
      @saved="handleSaved"
    />

    <!-- Delete skill confirm -->
    <ConfirmDialog
      :visible="!!deleteTarget"
      title="删除 Skill"
      :message="`确认删除 ${deleteTarget?.name}？此操作不可恢复，包含的 zip 文件也会被删除。`"
      @confirm="confirmDelete"
      @cancel="deleteTarget = null"
    />

    <!-- Delete category confirm -->
    <ConfirmDialog
      :visible="!!deleteCategoryTarget"
      title="删除分类"
      :message="`确认删除分类 ${deleteCategoryTarget?.name}？该分类下的 Skill 不会被删除，但需重新设置分类。`"
      @confirm="confirmDeleteCategory"
      @cancel="deleteCategoryTarget = null"
    />

    <!-- 新建分类 -->
    <div
      v-if="showCategoryForm"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
    >
      <div class="w-full max-w-sm rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">新建分类</h3>
        <div class="mb-3">
          <label class="mb-1 block text-sm font-medium text-slate-700">名称</label>
          <input
            v-model="categoryFormName"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            placeholder="如：legal / dev / office"
          />
        </div>
        <div class="mb-4">
          <label class="mb-1 block text-sm font-medium text-slate-700">描述（可选）</label>
          <input
            v-model="categoryFormDescription"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
          />
        </div>
        <div class="flex justify-end gap-3">
          <button
            class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
            @click="showCategoryForm = false"
          >
            取消
          </button>
          <button
            class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
            @click="handleCreateCategory"
          >
            创建
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
