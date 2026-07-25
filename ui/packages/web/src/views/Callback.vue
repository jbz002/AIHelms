<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@aihelms/shared'

const router = useRouter()
const { loginWithCode } = useAuth()
const errorMessage = ref('')

onMounted(async () => {
  const code = new URLSearchParams(window.location.search).get('code')
  if (!code) {
    router.replace({ name: 'Login' })
    return
  }
  try {
    await loginWithCode(code)
    // code 一次性：换完立即清掉 URL 参数，防刷新/后退重消费
    window.history.replaceState({}, '', window.location.pathname)
    router.push({ name: 'Identity' })
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'AI Hub 登录失败'
    setTimeout(() => router.replace({ name: 'Login' }), 1500)
  }
})
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-slate-50">
    <div class="text-center">
      <p v-if="errorMessage" class="text-sm text-red-500">{{ errorMessage }}</p>
      <p v-else class="text-sm text-slate-500">AI Hub 登录中...</p>
    </div>
  </div>
</template>
