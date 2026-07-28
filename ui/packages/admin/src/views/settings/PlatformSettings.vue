<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import {
  getPlatformSettings,
  updatePlatformSettings,
  getActiveModels,
  toast,
  type ActiveModel,
  type PlatformSettings,
} from '@aihelms/shared'
import { Loader2, Save } from 'lucide-vue-next'

const models = ref<ActiveModel[]>([])
const settings = ref<PlatformSettings | null>(null)
const selectedModelId = ref<number | null>(null)
const loading = ref(false)
const saving = ref(false)

const currentLabel = computed(() => {
  const m = models.value.find((x) => x.id === selectedModelId.value)
  if (m) return m.name
  return selectedModelId.value ? `#${selectedModelId.value}` : '未配置'
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const [s, ms] = await Promise.all([getPlatformSettings(), getActiveModels()])
    settings.value = s
    models.value = ms
    selectedModelId.value = s.default_model_id
  } catch (e) {
    toast.error((e as Error).message || '加载平台设置失败')
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (saving.value) return
  saving.value = true
  try {
    const s = await updatePlatformSettings({ default_model_id: selectedModelId.value })
    settings.value = s
    toast.success('平台默认模型已更新')
  } catch (e) {
    toast.error((e as Error).message || '更新失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-slate-900">平台设置</h1>
      <p class="mt-1 text-sm text-slate-500">
        平台级 LLM 调用（如文档库 AI 搜索总结）使用的默认模型
      </p>
    </div>

    <div v-if="loading" class="py-12 text-center text-sm text-slate-500">加载中...</div>

    <div v-else class="max-w-xl rounded-xl border border-slate-200 bg-white p-5">
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
          :disabled="saving"
          @click="save"
        >
          <Loader2 v-if="saving" class="h-4 w-4 animate-spin" />
          <Save v-else class="h-4 w-4" />
          保存
        </button>
      </div>
    </div>
  </div>
</template>
