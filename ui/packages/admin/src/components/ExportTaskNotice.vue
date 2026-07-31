<script setup lang="ts">
withDefaults(defineProps<{ message?: string }>(), {
  message: '导出任务已创建，点击「去下载」立即下载，或稍后点击右上角「导出任务」按钮查看',
})
</script>

<template>
  <div class="fixed bottom-6 right-6 z-50 flex max-w-md items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 shadow-lg">
    <span class="min-w-0 flex-1">{{ message }}</span>
    <RouterLink to="/export-tasks" class="shrink-0 rounded-md border border-emerald-300 bg-white px-3 py-1 text-xs font-semibold text-emerald-700 hover:bg-emerald-100">去下载</RouterLink>
  </div>
</template>
