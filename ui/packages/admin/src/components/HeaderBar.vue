<script setup lang="ts">
import { Menu } from 'lucide-vue-next'
import { useAuth } from '@aihelms/shared'

import AdminMcpStatus from './AdminMcpStatus.vue'

const { currentUser, logout } = useAuth()
const emit = defineEmits<{ toggleSidebar: [] }>()

function handleLogout(): void {
  logout()
}
</script>

<template>
  <header class="flex h-14 items-center justify-between gap-2 border-b border-slate-200/60 bg-white/70 px-3 backdrop-blur-lg sm:px-6">
    <div class="flex min-w-0 items-center gap-2">
      <button
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-600 transition-colors hover:bg-slate-100 md:hidden"
        type="button"
        title="打开导航"
        aria-label="打开导航"
        @click="emit('toggleSidebar')"
      >
        <Menu class="h-5 w-5" />
      </button>
      <div class="hidden min-w-0 truncate text-sm font-medium text-slate-700 sm:block">
        AIHelms 管理后台
      </div>
    </div>
    <div class="flex items-center gap-2 sm:gap-4">
      <AdminMcpStatus />
      <span class="hidden text-sm text-slate-600 sm:inline">{{ currentUser?.username }}</span>
      <button
        class="rounded-lg px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-slate-100/80"
        @click="handleLogout"
      >
        退出
      </button>
    </div>
  </header>
</template>
