<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  getAiPolicySignatures,
  replaceAiPolicySignatures,
  toast,
  type AiPolicySignatureRules,
} from '@aihelms/shared'

const loading = ref(false)
const rules = ref<AiPolicySignatureRules | null>(null)
const editOpen = ref(false)
const draft = ref('')
const saving = ref(false)

const severityLabel: Record<string, string> = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '提示',
}

function severityClass(severity?: string): string {
  if (severity === 'critical') return 'bg-red-50 text-red-700 ring-red-200'
  if (severity === 'high') return 'bg-orange-50 text-orange-700 ring-orange-200'
  if (severity === 'medium') return 'bg-amber-50 text-amber-700 ring-amber-200'
  if (severity === 'low') return 'bg-slate-100 text-slate-600 ring-slate-200'
  return 'bg-emerald-50 text-emerald-700 ring-emerald-200'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    rules.value = await getAiPolicySignatures()
  } catch (e) {
    toast.error((e as { message?: string }).message || '规则加载失败')
  } finally {
    loading.value = false
  }
}

function openEdit(): void {
  draft.value = rules.value?.content || ''
  editOpen.value = true
}

async function save(): Promise<void> {
  saving.value = true
  try {
    rules.value = await replaceAiPolicySignatures(draft.value)
    editOpen.value = false
    toast.success('规则集已更新')
  } catch (e) {
    toast.error((e as { message?: string }).message || '规则保存失败，请检查 YAML 格式')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-lg font-semibold text-slate-900">Regex 规则管理</h1>
        <p class="mt-1 text-sm text-slate-500">数据驱动的 Regex 签名规则，扫描时热加载。版本：{{ rules?.version || '-' }}</p>
      </div>
      <button class="inline-flex items-center gap-1 rounded-lg bg-purple-600 px-3 py-2 text-sm font-medium text-white hover:bg-purple-500" type="button" @click="openEdit">
        替换规则集
      </button>
    </div>

    <div v-if="loading" class="flex items-center justify-center gap-2 py-20 text-sm text-slate-400">
      加载中...
    </div>

    <section v-else-if="rules && rules.rules.length" class="space-y-3">
      <article v-for="rule in rules.rules" :key="rule.id" class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-mono text-xs text-slate-500">{{ rule.id }}</span>
          <span class="rounded-full px-2 py-0.5 text-xs font-medium ring-1" :class="severityClass(rule.severity)">{{ severityLabel[rule.severity] || rule.severity }}</span>
          <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">{{ rule.category }}</span>
          <span v-for="ft in rule.file_types" :key="ft" class="rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700 ring-1 ring-sky-200">{{ ft }}</span>
        </div>
        <h3 class="mt-2 text-sm font-semibold text-slate-900">{{ rule.title || rule.id }}</h3>
        <p v-if="rule.description" class="mt-1 text-sm text-slate-600">{{ rule.description }}</p>
        <pre class="mt-2 overflow-auto rounded-lg bg-slate-900 p-3 text-xs leading-5 text-slate-100">{{ rule.pattern }}</pre>
        <p v-if="rule.remediation" class="mt-2 text-sm text-slate-700">处理建议：{{ rule.remediation }}</p>
      </article>
    </section>

    <div v-else class="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-400">
      暂无规则
    </div>

    <section v-if="editOpen" class="rounded-xl border border-purple-200 bg-white p-5 shadow-sm">
      <h2 class="text-base font-semibold text-slate-900">替换规则集（YAML）</h2>
      <p class="mt-1 text-xs text-slate-500">粘贴完整 signatures.yaml 内容，保存前会做语法与字段校验。</p>
      <textarea v-model="draft" rows="18" class="mt-3 w-full rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-700" placeholder="version: 2026.07.21.1&#10;rules:&#10;  - id: REG-..." />
      <div class="mt-3 flex justify-end gap-2">
        <button class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:border-slate-300" type="button" @click="editOpen = false">取消</button>
        <button class="rounded-lg bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-500 disabled:opacity-50" :disabled="saving || !draft.trim()" type="button" @click="save">{{ saving ? '保存中' : '保存' }}</button>
      </div>
    </section>
  </div>
</template>
