<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import {
  createSkillVersionSecurityAudit,
  getAiPolicyAudit,
  toast,
  usePermission,
  type SkillVersion,
  type AiPolicyAudit,
} from '@aihelms/shared'
import MarkdownRenderer from '@aihelms/shared/src/components/MarkdownRenderer.vue'
import { ShieldCheck, X } from 'lucide-vue-next'
import VersionChip from './VersionChip.vue'

interface Props {
  skillId: number
  version: SkillVersion | null
}
const props = defineProps<Props>()
const emit = defineEmits<{ audited: [] }>()

const { hasPermission } = usePermission()
const canScan = hasPermission('ai_policies:scan')

const auditPolicy = ref<'balanced' | 'strict' | 'permissive'>('balanced')
const submitting = ref(false)
const showDrawer = ref(false)
const showAuditDialog = ref(false)
const auditDetail = ref<AiPolicyAudit | null>(null)
const reportLoading = ref(false)
const auditPolicyOptions: { v: 'balanced' | 'strict' | 'permissive'; name: string; desc: string }[] = [
  { v: 'balanced', name: '均衡策略', desc: '默认，兼顾覆盖与误报' },
  { v: 'strict', name: '严格策略', desc: '更多检查项，高风险零容忍' },
  { v: 'permissive', name: '宽松策略', desc: '仅高优先级风险检查' },
]

function securityBadge(v: SkillVersion): { cls: string; label: string } {
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

const badge = computed(() => (props.version ? securityBadge(props.version) : null))
const auditCode = computed(() => props.version?.latest_ai_policies_audit_code || '')
const running = computed(
  () => props.version?.security_status === 'queued' || props.version?.security_status === 'running',
)

async function loadReport(): Promise<void> {
  // 审查中 / 无报告 code → 不拉取（running 时后端尚无 markdown_report）
  if (!auditCode.value || running.value) {
    auditDetail.value = null
    return
  }
  // 已加载同 code 报告 → 跳过（防重开抽屉重复请求；版本切换时 watch 已清 auditDetail）
  if (auditDetail.value) return
  reportLoading.value = true
  try {
    auditDetail.value = await getAiPolicyAudit(auditCode.value)
  } catch (e) {
    toast.error((e as { message?: string }).message || '报告加载失败')
  } finally {
    reportLoading.value = false
  }
}

// 开抽屉 / 报告 code 变 / 审查状态变（完成自动刷新）→ 拉报告
watch(
  () => [showDrawer.value, auditCode.value, props.version?.security_status] as const,
  () => {
    if (showDrawer.value) loadReport()
  },
)

// 版本切换 → 关闭抽屉/对话框，复位
watch(
  () => props.version?.id,
  () => {
    showDrawer.value = false
    showAuditDialog.value = false
    auditPolicy.value = 'balanced'
    submitting.value = false
    auditDetail.value = null
  },
)

function openAuditDialog(): void {
  auditPolicy.value = 'balanced'
  showAuditDialog.value = true
}

async function confirmAudit(): Promise<void> {
  if (!props.version) return
  submitting.value = true
  try {
    await createSkillVersionSecurityAudit(props.skillId, props.version.id, auditPolicy.value)
    toast.success('已提交版本安全审查，完成后可激活')
    showAuditDialog.value = false
    auditDetail.value = null
    emit('audited')
  } catch (e) {
    toast.error((e as { message?: string }).message || '审查任务创建失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <button
    class="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
    @click="showDrawer = true"
  >
    <ShieldCheck class="h-3.5 w-3.5" /> 安全审查
  </button>

  <Teleport to="body">
    <div v-if="showDrawer" class="fixed inset-0 z-50">
      <div class="absolute inset-0 bg-black/30" @click="showDrawer = false" />
      <aside class="absolute right-0 top-0 flex h-full w-full max-w-3xl flex-col bg-white shadow-2xl">
        <div class="flex shrink-0 items-center justify-between border-b border-slate-200 px-5 py-3">
          <span class="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <ShieldCheck class="h-4 w-4 text-purple-500" /> 安全审查
            <VersionChip :version="version" />
          </span>
          <div class="flex items-center gap-2">
            <button
              v-if="version && canScan && !running"
              class="rounded-md bg-purple-50 px-2.5 py-1 text-xs font-medium text-purple-600 transition-colors hover:bg-purple-100"
              @click="openAuditDialog"
            >
              {{ version.security_status === 'not_scanned' || !version.security_status ? '发起审查' : '重新审查' }}
            </button>
            <button
              class="flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-100"
              aria-label="关闭"
              @click="showDrawer = false"
            >
              <X class="h-4 w-4" />
            </button>
          </div>
        </div>
        <div class="flex-1 overflow-y-auto px-5 py-4">
          <!-- 状态徽标 -->
          <div v-if="version" class="mb-4 flex flex-wrap items-center gap-2 text-xs">
            <span class="rounded px-1.5 py-0.5 font-medium" :class="badge!.cls">{{ badge!.label }}</span>
            <span v-if="running" class="text-slate-400">审查中…</span>
            <span v-if="!version.security_status || version.security_status === 'not_scanned'" class="text-slate-400">
              未审查版本不可激活
            </span>
          </div>
          <div v-else class="py-8 text-center text-sm text-gray-400">暂无版本</div>

          <!-- 报告内容 -->
          <div v-if="version">
            <div v-if="reportLoading" class="py-8 text-center text-sm text-gray-400">报告加载中…</div>
            <div v-else-if="running" class="py-8 text-center text-sm text-gray-400">
              审查进行中，完成后将自动刷新报告
            </div>
            <div v-else-if="!auditCode" class="py-8 text-center text-sm text-gray-400">
              该版本尚未发起安全审查
            </div>
            <MarkdownRenderer v-else-if="auditDetail?.markdown_report" :content="auditDetail.markdown_report" />
            <div v-else class="py-8 text-center text-sm text-gray-400">报告暂无内容</div>
          </div>
        </div>
      </aside>
    </div>
  </Teleport>

  <!-- 审查策略对话框 -->
  <Teleport to="body">
    <div v-if="showAuditDialog && version" class="fixed inset-0 z-[60] flex items-center justify-center bg-black/20">
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-2 text-lg font-semibold text-slate-900">
          AI Policies 安全审查 · v{{ version.version }}
        </h3>
        <p class="mb-3 text-xs text-slate-500">
          选择审查策略，对版本 <span class="font-mono">v{{ version.version }}</span> 的 zip 内容执行 AI Policies 检查，通过后方可激活。
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
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="showAuditDialog = false">取消</button>
          <button
            class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-500 disabled:opacity-50"
            :disabled="submitting"
            @click="confirmAudit"
          >{{ submitting ? '提交中…' : '开始审查' }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
