<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@aihelms/shared'

const router = useRouter()
const { login, redirectToAiHub } = useAuth()

const email = ref('')
const password = ref('')
const errorMessage = ref('')
const isLoading = ref(false)

function handleSso(): void {
  redirectToAiHub(
    import.meta.env.VITE_AI_HUB_URL,
    import.meta.env.VITE_AI_HUB_APP_CODE,
    '/auth/callback',
  )
}

async function handleLogin(): Promise<void> {
  if (!email.value || !password.value) {
    errorMessage.value = '请输入账号和密码'
    return
  }
  isLoading.value = true
  try {
    await login(email.value, password.value)
    errorMessage.value = ''
    router.push('/')
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '用户名或密码错误'
  } finally {
    isLoading.value = false
  }
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
      <div class="space-y-3">
        <button
          type="button"
          @click="handleSso"
          class="flex h-11 w-full items-center justify-center rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 transition-all hover:bg-slate-50 active:scale-[0.98]"
        >
          AI Hub 登录
        </button>
        <div class="flex items-center gap-3">
          <div class="h-px flex-1 bg-slate-200"></div>
          <span class="text-xs text-slate-400">或</span>
          <div class="h-px flex-1 bg-slate-200"></div>
        </div>
      </div>

      <!-- 表单 -->
      <form class="space-y-5" @submit.prevent="handleLogin">
        <div class="space-y-2">
          <label class="text-sm font-medium text-slate-700">账号</label>
          <input v-model="email" type="text"
            class="flex h-11 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-900 placeholder:text-slate-400 focus:border-purple-500/50 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
            placeholder="请输入邮箱或用户名" autocomplete="username" />
        </div>

        <div class="space-y-2">
          <label class="text-sm font-medium text-slate-700">密码</label>
          <input v-model="password" type="password"
            class="flex h-11 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-900 placeholder:text-slate-400 focus:border-purple-500/50 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
            placeholder="请输入密码" autocomplete="current-password" />
        </div>

        <p v-if="errorMessage" class="text-sm text-red-500">{{ errorMessage }}</p>

        <button type="submit" :disabled="isLoading"
          class="flex h-11 w-full items-center justify-center rounded-lg bg-gradient-to-r from-purple-600 to-blue-600 text-sm font-medium text-white shadow-md shadow-purple-500/20 transition-all hover:from-purple-500 hover:to-blue-500 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50">
          {{ isLoading ? '登录中...' : '登录' }}
        </button>
      </form>

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
