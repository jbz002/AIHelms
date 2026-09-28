<script setup lang="ts">
import { ref, watch } from 'vue'
import type { FullDepartmentItem } from '@aihelms/shared'

// Skill / MCP 发布设置共享弹窗：is_published / visibility_type / requires_approval。
// 可见性收敛两选（2026-09-28 决策）：公开 / 按部门 + 部门选择器。
interface Props {
  visible: boolean
  isPublished: boolean
  requiresApproval: boolean
  visibilityType: string
  departments: FullDepartmentItem[]
  visibleDepartmentId?: number | null
  loading?: boolean
  title?: string
  hint?: string
  errorMessage?: string
}

const props = withDefaults(defineProps<Props>(), {
  visibleDepartmentId: null,
  loading: false,
  title: '发布设置',
  hint: '设置资源在用户端的可见性与领用方式',
  errorMessage: '',
})

const emit = defineEmits<{
  close: []
  save: [
    payload: {
      is_published: boolean
      requires_approval: boolean
      visibility_type: string
      visible_department_id: number
    },
  ]
}>()

const localPublished = ref(false)
const localApproval = ref(false)
const localVisibility = ref('all')
const localDepartmentId = ref<number | null>(null)
const departmentError = ref('')

// 每次打开都以最新传入值重置，避免上次编辑残留
watch(
  () => props.visible,
  (v) => {
    if (v) {
      localPublished.value = props.isPublished
      localApproval.value = props.requiresApproval
      localVisibility.value = props.visibilityType || 'all'
      localDepartmentId.value = props.visibleDepartmentId ?? null
      departmentError.value = ''
    }
  },
)

const visibilityOptions: { value: string; label: string; desc: string }[] = [
  { value: 'all', label: '公开', desc: '进入市场列表，全员可用' },
  { value: 'department', label: '按部门', desc: '仅所选部门的成员可见' },
]

function handleSave(): void {
  if (localVisibility.value === 'department') {
    if (!localDepartmentId.value) {
      departmentError.value = '请选择部门'
      return
    }
    emit('save', {
      is_published: localPublished.value,
      // 未发布时审批无意义，强制 false
      requires_approval: localPublished.value ? localApproval.value : false,
      visibility_type: localVisibility.value,
      visible_department_id: localDepartmentId.value,
    })
    return
  }
  emit('save', {
    is_published: localPublished.value,
    requires_approval: localPublished.value ? localApproval.value : false,
    visibility_type: 'all',
    // 切离按部门时清空部门归属，避免孤儿部门 id
    visible_department_id: 0,
  })
}
</script>

<template>
  <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
    <div class="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
      <h3 class="mb-4 text-lg font-semibold text-slate-900">{{ title }}</h3>
      <p class="mb-4 text-xs text-slate-400">{{ hint }}</p>

      <!-- 发布开关 -->
      <div class="mb-4 flex items-center justify-between rounded-lg border border-slate-200 p-3">
        <div>
          <span class="text-sm font-medium text-slate-700">发布到用户端</span>
          <p class="text-xs text-slate-400">开启后用户可在用户端看到并申请此资源</p>
        </div>
        <button
          class="relative h-6 w-11 rounded-full transition-colors"
          :class="localPublished ? 'bg-green-500' : 'bg-slate-300'"
          @click="localPublished = !localPublished"
        >
          <span
            class="absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform"
            :class="localPublished ? 'left-[22px]' : 'left-0.5'"
          />
        </button>
      </div>

      <!-- 可见性 -->
      <div v-if="localPublished" class="mb-4">
        <label class="mb-1.5 block text-sm font-medium text-slate-700">可见性</label>
        <div class="space-y-2">
          <label
            v-for="opt in visibilityOptions"
            :key="opt.value"
            class="flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors"
            :class="localVisibility === opt.value ? 'border-purple-300 bg-purple-50 text-purple-700' : 'border-slate-200 text-slate-600'"
          >
            <input v-model="localVisibility" type="radio" :value="opt.value" class="h-4 w-4 text-purple-600" />
            <span>
              <span class="font-medium">{{ opt.label }}</span>
              <span class="ml-1 text-xs text-slate-400">{{ opt.desc }}</span>
            </span>
          </label>
        </div>
        <!-- 部门选择器（仅按部门可见时） -->
        <div v-if="localVisibility === 'department'" class="mt-2">
          <select
            v-model="localDepartmentId"
            class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 focus:border-purple-400 focus:outline-none"
          >
            <option :value="null" disabled>请选择部门</option>
            <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
          <p v-if="!departments.length" class="mt-1 text-xs text-amber-500">部门列表为空，请先在组织管理同步 AI Hub 部门</p>
          <p v-if="departmentError" class="mt-1 text-xs text-red-500">{{ departmentError }}</p>
        </div>
      </div>

      <!-- 领用审批 -->
      <div v-if="localPublished" class="mb-4 flex items-center gap-2 rounded-lg border border-slate-200 p-3">
        <input
          v-model="localApproval"
          type="checkbox"
          class="h-4 w-4 rounded border-slate-300 text-purple-600 focus:ring-purple-500/20"
        />
        <div>
          <span class="text-sm font-medium text-slate-700">领用前需要审批</span>
          <p class="text-xs text-slate-400">开启后用户申请使用需管理员审批</p>
        </div>
      </div>

      <p v-if="errorMessage" class="mb-3 text-sm text-red-500">{{ errorMessage }}</p>

      <div class="flex justify-end gap-3">
        <button
          class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-200"
          @click="emit('close')"
        >
          取消
        </button>
        <button
          class="rounded-lg bg-gradient-to-r from-purple-600 to-blue-600 px-4 py-2 text-sm font-medium text-white shadow-md shadow-purple-500/20 transition-all hover:from-purple-500 hover:to-blue-500 active:scale-[0.98] disabled:opacity-50"
          :disabled="loading"
          @click="handleSave"
        >
          {{ loading ? '保存中...' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>
