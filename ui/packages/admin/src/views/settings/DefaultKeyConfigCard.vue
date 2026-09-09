<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Loader2, Save } from 'lucide-vue-next'
import { toast } from '@aihelms/shared'
import type { PlatformSettings } from '@aihelms/shared'

export interface DefaultKeyConfigPayload {
  default_key_budget_limit: number | null
  default_key_budget_hard_limit: boolean
  default_key_budget_duration: string
  default_key_rate_limit_mode: 'none' | 'total'
  default_key_tpm_limit: number | null
  default_key_rpm_limit: number | null
  default_key_max_parallel_requests: number | null
}

const props = defineProps<{ initial: PlatformSettings | null; saving: boolean }>()
const emit = defineEmits<{ save: [payload: DefaultKeyConfigPayload] }>()

const budgetEnabled = ref(false)
const rateEnabled = ref(false)
const budget = reactive({
  limit: null as number | null,
  duration: '30d',
  hardLimit: false,
})
const rate = reactive({
  tpm: null as number | null,
  rpm: null as number | null,
  parallel: null as number | null,
})

const durationOptions = [
  { value: '1d', label: '每日 (1d)' },
  { value: '7d', label: '每周 (7d)' },
  { value: '30d', label: '每月 (30d)' },
]

watch(
  () => props.initial,
  (s) => {
    if (!s) return
    budgetEnabled.value = s.default_key_budget_limit !== null
    budget.limit = s.default_key_budget_limit !== null ? parseFloat(s.default_key_budget_limit) : null
    budget.duration = s.default_key_budget_duration || '30d'
    budget.hardLimit = s.default_key_budget_hard_limit
    rateEnabled.value = s.default_key_rate_limit_mode === 'total'
    rate.tpm = s.default_key_tpm_limit
    rate.rpm = s.default_key_rpm_limit
    rate.parallel = s.default_key_max_parallel_requests
  },
  { immediate: true },
)

const isRateEmpty = computed(
  () => rate.tpm === null && rate.rpm === null && rate.parallel === null,
)

function handleSave(): void {
  if (rateEnabled.value && isRateEmpty.value) {
    toast.error('限流启用时 TPM/RPM/最大并发至少填写一项')
    return
  }
  if (budgetEnabled.value && (budget.limit === null || budget.limit < 0)) {
    toast.error('请填写有效的预算金额（≥0）')
    return
  }
  emit('save', {
    default_key_budget_limit: budgetEnabled.value ? budget.limit : null,
    default_key_budget_hard_limit: budgetEnabled.value ? budget.hardLimit : false,
    default_key_budget_duration: budget.duration,
    default_key_rate_limit_mode: rateEnabled.value ? 'total' : 'none',
    default_key_tpm_limit: rateEnabled.value ? rate.tpm : null,
    default_key_rpm_limit: rateEnabled.value ? rate.rpm : null,
    default_key_max_parallel_requests: rateEnabled.value ? rate.parallel : null,
  })
}
</script>

<template>
  <div class="max-w-xl rounded-xl border border-slate-200 bg-white p-5">
    <h2 class="text-base font-semibold text-slate-900">新用户默认 Key 配置</h2>
    <p class="mt-1 text-xs text-slate-500">
      新用户落地时（后台建用户 / SSO 首次登录 / 集成通道）自动创建的个人主 Key 将套用以下配置。
      不影响管理员手动创建的 Key，也不会回填已有用户的 Key。
    </p>

    <div class="mt-4 space-y-4">
      <div class="rounded-lg border border-slate-200/70 p-3">
        <label class="flex items-center gap-2 text-sm font-medium text-slate-700">
          <input v-model="budgetEnabled" type="checkbox" class="h-4 w-4 rounded border-slate-300" />
          默认预算
        </label>
        <div v-if="budgetEnabled" class="mt-3 grid grid-cols-2 gap-3">
          <label class="text-xs text-slate-500">预算金额 (¥)
            <input
              v-model.number="budget.limit"
              type="number"
              min="0"
              step="0.01"
              placeholder="如 38.5"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </label>
          <label class="text-xs text-slate-500">预算周期
            <select
              v-model="budget.duration"
              class="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            >
              <option v-for="opt in durationOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </label>
          <label class="col-span-2 flex items-center gap-2 text-xs text-slate-600">
            <input v-model="budget.hardLimit" type="checkbox" class="h-4 w-4 rounded border-slate-300" />
            超预算硬阻断（周期内花费达到上限后自动封禁，7d 周期每周一 00:00 清零，或预算上调后自动解封）
          </label>
        </div>
        <p v-else class="mt-2 text-xs text-slate-400">关闭后新用户主 Key 不设预算</p>
      </div>

      <div class="rounded-lg border border-slate-200/70 p-3">
        <label class="flex items-center gap-2 text-sm font-medium text-slate-700">
          <input v-model="rateEnabled" type="checkbox" class="h-4 w-4 rounded border-slate-300" />
          默认限流（总限流）
        </label>
        <div v-if="rateEnabled" class="mt-3 grid grid-cols-3 gap-3">
          <label class="text-xs text-slate-500">TPM
            <input
              v-model.number="rate.tpm"
              type="number"
              min="1"
              placeholder="不限"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </label>
          <label class="text-xs text-slate-500">RPM
            <input
              v-model.number="rate.rpm"
              type="number"
              min="1"
              placeholder="不限"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </label>
          <label class="text-xs text-slate-500">最大并发
            <input
              v-model.number="rate.parallel"
              type="number"
              min="1"
              placeholder="不限"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </label>
        </div>
        <p v-else class="mt-2 text-xs text-slate-400">关闭后新用户主 Key 不限流</p>
      </div>
    </div>

    <div class="mt-4 flex justify-end">
      <button
        class="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-60"
        :disabled="saving"
        @click="handleSave"
      >
        <Loader2 v-if="saving" class="h-4 w-4 animate-spin" />
        <Save v-else class="h-4 w-4" />
        保存默认配置
      </button>
    </div>
  </div>
</template>
