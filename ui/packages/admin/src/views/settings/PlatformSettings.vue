<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import {
  getPlatformSettings,
  updatePlatformSettings,
  getActiveModels,
  toast,
  type ActiveModel,
  type PlatformSettings,
  type UpdatePlatformSettingsParams,
} from '@aihelms/shared'
import { Loader2, Save } from 'lucide-vue-next'
import DefaultKeyConfigCard, {
  type DefaultKeyConfigPayload,
} from './DefaultKeyConfigCard.vue'

const models = ref<ActiveModel[]>([])
const settings = ref<PlatformSettings | null>(null)
const selectedModelId = ref<number | null>(null)
const loading = ref(false)
const savingModel = ref(false)
const savingKeyConfig = ref(false)

const currentLabel = computed(() => {
  const m = models.value.find((x) => x.id === selectedModelId.value)
  if (m) return m.name
  return selectedModelId.value ? `#${selectedModelId.value}` : '未配置'
})

// PUT 为全量替换：任一卡片保存都必须带上另一部分的现有值
let lastKeyConfig: DefaultKeyConfigPayload | null = null

function keyConfigFromSettings(s: PlatformSettings): DefaultKeyConfigPayload {
  return {
    default_key_budget_limit:
      s.default_key_budget_limit !== null ? parseFloat(s.default_key_budget_limit) : null,
    default_key_budget_hard_limit: s.default_key_budget_hard_limit,
    default_key_budget_duration: s.default_key_budget_duration || '30d',
    default_key_rate_limit_mode: s.default_key_rate_limit_mode,
    default_key_tpm_limit: s.default_key_tpm_limit,
    default_key_rpm_limit: s.default_key_rpm_limit,
    default_key_max_parallel_requests: s.default_key_max_parallel_requests,
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [s, ms] = await Promise.all([getPlatformSettings(), getActiveModels()])
    settings.value = s
    models.value = ms
    selectedModelId.value = s.default_model_id
    lastKeyConfig = keyConfigFromSettings(s)
  } catch (e) {
    toast.error((e as Error).message || '加载平台设置失败')
  } finally {
    loading.value = false
  }
}

async function saveModel(): Promise<void> {
  if (savingModel.value) return
  savingModel.value = true
  try {
    const s = await updatePlatformSettings({
      default_model_id: selectedModelId.value,
      ...(lastKeyConfig ?? keyConfigFromSettings(settings.value!)),
    })
    settings.value = s
    lastKeyConfig = keyConfigFromSettings(s)
    toast.success('平台默认模型已更新')
  } catch (e) {
    toast.error((e as Error).message || '更新失败')
  } finally {
    savingModel.value = false
  }
}

async function handleKeyConfigSave(payload: DefaultKeyConfigPayload): Promise<void> {
  if (savingKeyConfig.value) return
  savingKeyConfig.value = true
  try {
    const s = await updatePlatformSettings({
      default_model_id: selectedModelId.value,
      ...payload,
    } satisfies UpdatePlatformSettingsParams)
    settings.value = s
    lastKeyConfig = keyConfigFromSettings(s)
    toast.success('新用户默认 Key 配置已更新')
  } catch (e) {
    toast.error((e as Error).message || '更新失败')
  } finally {
    savingKeyConfig.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-slate-900">平台设置</h1>
      <p class="mt-1 text-sm text-slate-500">平台默认模型与新用户默认 Key 配置</p>
    </div>

    <div v-if="loading" class="py-12 text-center text-sm text-slate-500">加载中...</div>

    <div v-else class="space-y-5">
      <div class="max-w-xl rounded-xl border border-slate-200 bg-white p-5">
        <label class="block text-sm font-medium text-slate-700">平台默认模型</label>
        <p class="mt-1 text-xs text-slate-500">
          文档库 AI 搜索总结等平台调用将使用此模型。未配置时调用会提示「平台未配置默认模型」。
        </p>
        <select
          v-model.number="selectedModelId"
          class="mt-3 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
        >
          <option :value="null">未配置</option>
          <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}</option>
        </select>

        <div class="mt-3 rounded-md bg-slate-50 p-3 text-xs text-slate-600">
          <div>当前生效：{{ currentLabel }}</div>
          <div v-if="settings && !settings.default_model_id && settings.env_default_model_id" class="mt-1">
            env 兜底值 PLATFORM_DEFAULT_MODEL_ID = {{ settings.env_default_model_id }}
          </div>
          <div v-if="settings?.updated_at" class="mt-1">
            上次更新：{{ settings.updated_at.replace('T', ' ').slice(0, 19) }}
          </div>
        </div>

        <div class="mt-4 flex justify-end">
          <button
            class="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-60"
            :disabled="savingModel"
            @click="saveModel"
          >
            <Loader2 v-if="savingModel" class="h-4 w-4 animate-spin" />
            <Save v-else class="h-4 w-4" />
            保存
          </button>
        </div>
      </div>

      <DefaultKeyConfigCard
        :initial="settings"
        :saving="savingKeyConfig"
        @save="handleKeyConfigSave"
      />
    </div>
  </div>
</template>
