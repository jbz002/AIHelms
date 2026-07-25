<script setup lang="ts">
import { useAuth } from '@aihelms/shared'

const { redirectToAiHub } = useAuth()

function handleSso(): void {
  redirectToAiHub(
    import.meta.env.VITE_AI_HUB_URL,
    import.meta.env.VITE_AI_HUB_APP_CODE,
    '/admin/auth/callback',
  )
}
</script>

<template>
  <div class="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50">
    <!-- 毛玻璃卡片 -->
    <div
      class="relative z-10 w-full max-w-[420px] rounded-2xl border border-slate-200/60 bg-white p-8 shadow-xl"
    >
      <!-- Logo + 欢迎语 -->
      <div class="mb-8 space-y-3 text-center">
        <img src="/static/img/logo.png" alt="AIHelms" class="mx-auto h-8" />
        <h1 class="text-2xl font-semibold tracking-tight text-slate-900">欢迎回来</h1>
        <p class="text-sm text-slate-500">承载 AI 数字资产 · 释放AI生产力 · 链接未来</p>
      </div>

      <!-- AI Hub SSO 登录 -->
      <button
        type="button"
        @click="handleSso"
        class="flex h-11 w-full items-center justify-center rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 transition-all hover:bg-slate-50 active:scale-[0.98]"
      >
        AI Hub 登录
      </button>

      <!-- 底部说明 -->
      <p class="mt-6 text-center text-xs text-slate-400">
        前往
        <a href="/" class="text-purple-600 hover:underline">用户端</a>
      </p>
    </div>

    <!-- 版权信息 -->
    <p class="absolute bottom-6 left-1/2 -translate-x-1/2 text-xs text-slate-400">
      &copy; {{ new Date().getFullYear() }} AIHelms. All rights reserved.
    </p>
  </div>
</template>
