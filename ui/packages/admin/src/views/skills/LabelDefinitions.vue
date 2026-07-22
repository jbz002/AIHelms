<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  listLabelDefinitions,
  createLabelDefinition,
  updateLabelDefinition,
  deleteLabelDefinition,
  toast,
  LabelBadge,
  type LabelDefinition,
} from '@aihelms/shared'
import { Award, Plus } from 'lucide-vue-next'

const defs = ref<LabelDefinition[]>([])
const loading = ref(false)
const showEditor = ref(false)
const editing = ref<LabelDefinition | null>(null)
const saving = ref(false)

const form = ref({
  name: '',
  display_name_key: '',
  color: 'slate',
  sort_order: 0,
  is_active: true,
})

const COLORS = ['green', 'blue', 'purple', 'amber', 'red', 'slate']

async function load(): Promise<void> {
  loading.value = true
  try {
    defs.value = await listLabelDefinitions(false)
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openCreate(): void {
  editing.value = null
  form.value = { name: '', display_name_key: '', color: 'slate', sort_order: 0, is_active: true }
  showEditor.value = true
}

function openEdit(d: LabelDefinition): void {
  editing.value = d
  form.value = {
    name: d.name,
    display_name_key: d.display_name_key,
    color: d.color || 'slate',
    sort_order: d.sort_order,
    is_active: d.is_active,
  }
  showEditor.value = true
}

async function handleSave(): Promise<void> {
  if (!form.value.name.trim() || !form.value.display_name_key.trim()) {
    toast.error('请填写 name 与 display_name_key')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await updateLabelDefinition(editing.value.id, {
        display_name_key: form.value.display_name_key.trim(),
        color: form.value.color,
        sort_order: form.value.sort_order,
        is_active: form.value.is_active,
      })
      toast.success('标签定义已更新')
    } else {
      await createLabelDefinition({
        name: form.value.name.trim(),
        display_name_key: form.value.display_name_key.trim(),
        color: form.value.color,
        sort_order: form.value.sort_order,
        is_active: form.value.is_active,
      })
      toast.success('标签定义已创建')
    }
    showEditor.value = false
    await load()
  } catch (e) {
    toast.error((e as { message?: string }).message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleDeactivate(d: LabelDefinition): Promise<void> {
  try {
    await deleteLabelDefinition(d.id)
    toast.success(`标签 ${d.name} 已停用`)
    await load()
  } catch (e) {
    toast.error((e as { message?: string }).message || '停用失败')
  }
}
</script>

<template>
  <div class="mx-auto max-w-4xl p-6">
    <div class="mb-4 flex items-center justify-between">
      <h2 class="flex items-center gap-2 text-lg font-semibold text-slate-900">
        <Award class="h-5 w-5 text-amber-500" /> 治理标签定义
      </h2>
      <button
        class="flex items-center gap-1 rounded-md bg-purple-50 px-3 py-1.5 text-sm font-medium text-purple-600 hover:bg-purple-100"
        @click="openCreate"
      >
        <Plus class="h-4 w-4" /> 新建标签
      </button>
    </div>
    <p class="mb-4 text-xs text-slate-400">
      治理标签（recommended/official/verified 等）作为市场显式标注位，不进质量分。删除为软停用，保留已授予记录的引用完整性。display_name_key 走前端 i18n（shared common.json）。
    </p>

    <div v-if="loading" class="py-8 text-center text-sm text-slate-400">加载中...</div>
    <div v-else class="overflow-hidden rounded-xl border border-slate-200">
      <table class="w-full text-sm">
        <thead class="bg-slate-50 text-left text-xs text-slate-500">
          <tr>
            <th class="px-4 py-2 font-medium">预览</th>
            <th class="px-4 py-2 font-medium">name</th>
            <th class="px-4 py-2 font-medium">i18n key</th>
            <th class="px-4 py-2 font-medium">颜色</th>
            <th class="px-4 py-2 font-medium">排序</th>
            <th class="px-4 py-2 font-medium">状态</th>
            <th class="px-4 py-2 font-medium">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-for="d in defs" :key="d.id" class="text-slate-700">
            <td class="px-4 py-2"><LabelBadge :name="d.name" :display_name_key="d.display_name_key" :color="d.color" size="sm" /></td>
            <td class="px-4 py-2 font-mono text-xs">{{ d.name }}</td>
            <td class="px-4 py-2 font-mono text-xs text-slate-500">{{ d.display_name_key }}</td>
            <td class="px-4 py-2 text-xs">{{ d.color || '—' }}</td>
            <td class="px-4 py-2 text-xs">{{ d.sort_order }}</td>
            <td class="px-4 py-2">
              <span class="rounded px-1.5 py-0.5 text-[10px]" :class="d.is_active ? 'bg-green-50 text-green-600' : 'bg-slate-100 text-slate-400'">
                {{ d.is_active ? '启用' : '停用' }}
              </span>
            </td>
            <td class="px-4 py-2">
              <div class="flex gap-2">
                <button class="text-xs text-purple-600 hover:underline" @click="openEdit(d)">编辑</button>
                <button
                  v-if="d.is_active"
                  class="text-xs text-red-500 hover:underline"
                  @click="handleDeactivate(d)"
                >停用</button>
              </div>
            </td>
          </tr>
          <tr v-if="!defs.length">
            <td colspan="7" class="px-4 py-8 text-center text-xs text-slate-400">暂无标签定义</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="showEditor" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">
          {{ editing ? '编辑标签定义' : '新建标签定义' }}
        </h3>
        <div class="space-y-3">
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-600">name（小写字母/数字/下划线）</label>
            <input
              v-model="form.name"
              :disabled="!!editing"
              placeholder="如 recommended"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none disabled:bg-slate-50"
            />
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-600">display_name_key（i18n）</label>
            <input
              v-model="form.display_name_key"
              placeholder="如 label.recommended.title"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block text-xs font-medium text-slate-600">颜色</label>
              <select v-model="form.color" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none">
                <option v-for="c in COLORS" :key="c" :value="c">{{ c }}</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block text-xs font-medium text-slate-600">排序</label>
              <input v-model.number="form.sort_order" type="number" class="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-purple-500 focus:outline-none" />
            </div>
          </div>
          <label class="flex items-center gap-2 text-sm text-slate-700">
            <input v-model="form.is_active" type="checkbox" class="h-4 w-4 rounded border-slate-300" /> 启用
          </label>
        </div>
        <div class="mt-5 flex justify-end gap-3">
          <button class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700 hover:bg-slate-200" @click="showEditor = false">取消</button>
          <button
            class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            :disabled="saving"
            @click="handleSave"
          >
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
