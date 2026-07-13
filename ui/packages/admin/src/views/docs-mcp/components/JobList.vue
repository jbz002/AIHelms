<script setup lang="ts">
import { ref } from 'vue'
import type { DocsMcpJob } from '@aihelms/shared'
import { Trash2, Loader2 } from 'lucide-vue-next'
import JobItem from './JobItem.vue'

interface Props {
  jobs: DocsMcpJob[]
}

interface Emits {
  cancel: [jobId: string]
  clearCompleted: []
}

defineProps<Props>()
const emit = defineEmits<Emits>()
const clearing = ref(false)

async function handleClear(): Promise<void> {
  clearing.value = true
  try {
    emit('clearCompleted')
  } finally {
    setTimeout(() => {
      clearing.value = false
    }, 500)
  }
}
</script>

<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h3 class="text-sm font-semibold text-gray-700">任务队列</h3>
      <button
        class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        :disabled="clearing"
        @click="handleClear"
      >
        <Loader2 v-if="clearing" class="h-3 w-3 animate-spin" />
        <Trash2 v-else class="h-3 w-3" />
        清理已完成
      </button>
    </div>
    <div v-if="jobs.length === 0" class="rounded-lg border border-dashed border-gray-200 py-8 text-center">
      <p class="text-sm text-gray-400">暂无任务</p>
    </div>
    <div v-else class="space-y-2">
      <JobItem
        v-for="job in jobs"
        :key="job.id"
        :job="job"
        @cancel="(id) => emit('cancel', id)"
      />
    </div>
  </div>
</template>
