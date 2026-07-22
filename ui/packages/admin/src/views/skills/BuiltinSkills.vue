<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  getBuiltinSkills,
  getBuiltinSkillsStatus,
  syncBuiltinSkills,
  toast,
  LabelBadge,
  type BuiltinSkillStatusEntry,
  type Skill,
} from '@aihelms/shared'
import { Package, RefreshCw } from 'lucide-vue-next'

const status = ref<BuiltinSkillStatusEntry[]>([])
const skills = ref<Skill[]>([])
const loading = ref(false)
const syncing = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const [s, list] = await Promise.all([getBuiltinSkillsStatus(), getBuiltinSkills()])
    status.value = s
    skills.value = list.items
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function handleSync(): Promise<void> {
  syncing.value = true
  try {
    await syncBuiltinSkills()
    toast.success('同步任务已派发，稍后刷新查看结果')
  } catch (e) {
    toast.error((e as { message?: string }).message || '派发失败')
  } finally {
    syncing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-4xl p-6">
    <div class="mb-4 flex items-center justify-between">
      <h2 class="flex items-center gap-2 text-lg font-semibold text-slate-900">
        <Package class="h-5 w-5 text-blue-500" /> 内置 Skills
      </h2>
      <button
        class="flex items-center gap-1 rounded-md bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-600 hover:bg-blue-100 disabled:opacity-50"
        :disabled="syncing"
        @click="handleSync"
      >
        <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': syncing }" /> 重新同步
      </button>
    </div>
    <p class="mb-4 text-xs text-slate-400">
      实例启动时按 manifest 自动同步官方 skill 到全局（复用标准发布链路 + official Label），开箱即用。幂等：slug+version 已存在则跳过；sha256 与 manifest 不一致则拒绝。
    </p>

    <div v-if="loading" class="py-8 text-center text-sm text-slate-400">加载中...</div>
    <template v-else>
      <h3 class="mb-2 text-sm font-semibold text-slate-700">Manifest 同步状态</h3>
      <div class="mb-6 overflow-hidden rounded-xl border border-slate-200">
        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th class="px-4 py-2 font-medium">slug</th>
              <th class="px-4 py-2 font-medium">名称</th>
              <th class="px-4 py-2 font-medium">版本</th>
              <th class="px-4 py-2 font-medium">分类</th>
              <th class="px-4 py-2 font-medium">状态</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="row in status" :key="row.slug" class="text-slate-700">
              <td class="px-4 py-2 font-mono text-xs">{{ row.slug }}</td>
              <td class="px-4 py-2">{{ row.name }}</td>
              <td class="px-4 py-2 text-xs">{{ row.version }}</td>
              <td class="px-4 py-2 text-xs">{{ row.category }}</td>
              <td class="px-4 py-2">
                <span
                  class="rounded px-1.5 py-0.5 text-[10px]"
                  :class="row.synced ? 'bg-green-50 text-green-600' : 'bg-amber-50 text-amber-600'"
                >
                  {{ row.synced ? '已同步' : '未同步' }}
                </span>
              </td>
            </tr>
            <tr v-if="!status.length">
              <td colspan="5" class="px-4 py-8 text-center text-xs text-slate-400">manifest 为空或不可读</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3 class="mb-2 text-sm font-semibold text-slate-700">已入库内置 Skill（{{ skills.length }}）</h3>
      <div class="overflow-hidden rounded-xl border border-slate-200">
        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th class="px-4 py-2 font-medium">名称</th>
              <th class="px-4 py-2 font-medium">slug</th>
              <th class="px-4 py-2 font-medium">版本</th>
              <th class="px-4 py-2 font-medium">标签</th>
              <th class="px-4 py-2 font-medium">发布</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="s in skills" :key="s.id" class="text-slate-700">
              <td class="px-4 py-2">{{ s.name }}</td>
              <td class="px-4 py-2 font-mono text-xs">{{ s.builtin_slug }}</td>
              <td class="px-4 py-2 text-xs">{{ s.version }}</td>
              <td class="px-4 py-2">
                <LabelBadge
                  v-for="lb in s.labels"
                  :key="lb.id"
                  :name="lb.name"
                  :display_name_key="lb.display_name_key"
                  :color="lb.color"
                  size="sm"
                />
              </td>
              <td class="px-4 py-2">
                <span
                  class="rounded px-1.5 py-0.5 text-[10px]"
                  :class="s.is_published ? 'bg-green-50 text-green-600' : 'bg-slate-100 text-slate-400'"
                >
                  {{ s.is_published ? '已发布' : '未发布' }}
                </span>
              </td>
            </tr>
            <tr v-if="!skills.length">
              <td colspan="5" class="px-4 py-8 text-center text-xs text-slate-400">暂无内置 Skill，点击「重新同步」</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
