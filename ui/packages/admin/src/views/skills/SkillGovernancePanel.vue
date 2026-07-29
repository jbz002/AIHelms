<script setup lang="ts">
import { ref } from 'vue'
import { setSkillHidden, toast, type Skill } from '@aihelms/shared'
import { Award } from 'lucide-vue-next'

interface Props {
  skill: Skill
}

const props = defineProps<Props>()
const emit = defineEmits<{
  changed: []
}>()

const toggling = ref(false)

async function handleToggleHidden(): Promise<void> {
  toggling.value = true
  try {
    const next = !props.skill.hidden
    await setSkillHidden(props.skill.id, next)
    toast.success(next ? '已治理下架' : '已恢复上架')
    emit('changed')
  } catch (e) {
    toast.error((e as { message?: string }).message || '操作失败')
  } finally {
    toggling.value = false
  }
}
</script>

<template>
  <div class="mb-4 rounded-xl border border-slate-200/60 p-3">
    <h4 class="mb-3 flex items-center gap-1.5 text-sm font-semibold text-slate-900">
      <Award class="h-4 w-4 text-amber-500" />
      治理
    </h4>

    <!-- 治理下架 -->
    <div class="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2">
      <div>
        <p class="text-sm font-medium text-slate-700">治理下架（hidden）</p>
        <p class="text-xs text-slate-400">与发布开关、可见性正交。下架后非管理员不可见。</p>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="skill.hidden" class="rounded bg-red-50 px-1.5 py-0.5 text-[10px] text-red-600">已下架</span>
        <button
          class="rounded-md px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50"
          :class="skill.hidden ? 'bg-slate-200 text-slate-600 hover:bg-slate-300' : 'bg-red-50 text-red-600 hover:bg-red-100'"
          :disabled="toggling"
          @click="handleToggleHidden"
        >
          {{ skill.hidden ? '恢复上架' : '下架' }}
        </button>
      </div>
    </div>
  </div>
</template>
