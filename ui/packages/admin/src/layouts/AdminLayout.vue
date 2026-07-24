<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAuth } from '@aihelms/shared'
import Sidebar from '../components/Sidebar.vue'
import HeaderBar from '../components/HeaderBar.vue'

const { fetchCurrentUser } = useAuth()
const sidebarOpen = ref(false)

onMounted(async () => {
  await fetchCurrentUser()
})
</script>

<template>
  <div class="relative flex h-screen overflow-hidden bg-slate-50">
    <!-- 侧边栏 -->
    <Sidebar :open="sidebarOpen" @close="sidebarOpen = false" />
    <button
      v-if="sidebarOpen"
      class="fixed inset-0 z-30 bg-slate-950/35 md:hidden"
      type="button"
      aria-label="关闭导航遮罩"
      @click="sidebarOpen = false"
    />

    <!-- 右侧内容区 -->
    <div class="relative z-10 flex flex-1 flex-col overflow-hidden">
      <HeaderBar @toggle-sidebar="sidebarOpen = !sidebarOpen" />
      <main class="flex-1 overflow-y-auto p-4 sm:p-6">
        <RouterView />
      </main>
    </div>
  </div>
</template>
