<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@aihelms/shared'

const router = useRouter()
const { loginWithCode, loginWithTicket } = useAuth()
const errorMessage = ref('')

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  const code = params.get('code')
  const ticket = params.get('ticket')
  if (!code && !ticket) {
    router.replace({ name: 'Login' })
    return
  }
  try {
    if (code) {
      await loginWithCode(code)
    } else if (ticket) {
      await loginWithTicket(ticket)
    }
    // code/ticket 一次性：换完立即清掉 URL 参数，防刷新/后退重消费
    window.history.replaceState({}, '', window.location.pathname)
    router.push('/')
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
