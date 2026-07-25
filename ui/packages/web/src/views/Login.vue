<script setup lang="ts">
import { useAuth } from '@aihelms/shared'

const { redirectToAiHub } = useAuth()

function handleSso(): void {
  redirectToAiHub(
    import.meta.env.VITE_AI_HUB_URL,
    import.meta.env.VITE_AI_HUB_APP_CODE,
    '/auth/callback',
  )
}
</script>

<template>
  <div class="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50">
    <!-- 毛玻璃卡片 -->
    <div class="relative z-10 w-full max-w-[420px] rounded-2xl border border-slate-200/60 bg-white p-8 shadow-xl">
      <!-- Logo -->
      <div class="mb-8 space-y-3 text-center">
        <div class="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-600 to-blue-600 text-sm font-bold text-white shadow-lg shadow-purple-500/30">
          AI
        </div>
        <h1 class="text-2xl font-semibold tracking-tight text-slate-900">欢迎回来</h1>
        <p class="text-sm text-slate-500">登录你的 AI 身份</p>
      </div>

      <!-- AI Hub SSO 登录 -->
      <button
        type="button"
        @click="handleSso"
        class="flex h-11 w-full items-center justify-center rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 transition-all hover:bg-slate-50 active:scale-[0.98]"
      >
        AI Hub 登录
      </button>

      <!-- 底部切换 -->
      <p class="mt-6 text-center text-xs text-slate-400">
        管理员？
        <a href="/admin/login" class="text-purple-600 hover:underline">切换到管理后台</a>
      </p>
    </div>

    <!-- 版权信息 -->
    <p class="absolute bottom-6 left-1/2 -translate-x-1/2 text-xs text-slate-400">
      &copy; {{ new Date().getFullYear() }} AIHelms. All rights reserved.
    </p>
  </div>
</template>
