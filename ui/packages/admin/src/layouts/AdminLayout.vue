<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuth } from '@aihelms/shared'
import Sidebar from '../components/Sidebar.vue'
import HeaderBar from '../components/HeaderBar.vue'

const { fetchCurrentUser } = useAuth()

onMounted(async () => {
  await fetchCurrentUser()
})
</script>

<template>
  <div class="relative flex h-screen overflow-hidden bg-slate-50">
    <!-- 侧边栏 -->
    <Sidebar />

    <!-- 右侧内容区 -->
    <div class="relative z-10 flex flex-1 flex-col overflow-hidden">
      <HeaderBar />
      <main class="flex-1 overflow-y-auto p-6">
        <RouterView />
      </main>
    </div>
  </div>
</template>
