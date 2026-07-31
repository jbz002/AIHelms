<script setup lang="ts">
import { onMounted, onUnmounted, ref, nextTick, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuth, usePermission } from '@aihelms/shared'
import { LogOut, Settings, ChevronDown, KeyRound } from 'lucide-vue-next'
import LanguageSwitcher from '@aihelms/shared/src/components/LanguageSwitcher.vue'

const router = useRouter()
const { t } = useI18n()
const { currentUser, fetchCurrentUser, logout } = useAuth()
const { hasPermission } = usePermission()

onMounted(async () => {
  if (!currentUser.value) {
    await fetchCurrentUser()
  }
  document.addEventListener('click', handleGlobalClick, true)
})

onUnmounted(() => {
  document.removeEventListener('click', handleGlobalClick, true)
})

function handleGlobalClick(e: MouseEvent): void {
  const trigger = triggerRef.value
  const dropdown = dropdownRef.value
  const target = e.target as Node
  if (showDropdown.value && trigger && !trigger.contains(target) && (!dropdown || !dropdown.contains(target))) {
    showDropdown.value = false
  }
}

function handleLogout(): void {
  logout()
}

const currentPath = ref(router.currentRoute.value.path)
router.afterEach((to) => {
  currentPath.value = to.path
})

function isActive(path: string): boolean {
  if (path === '/') return currentPath.value === '/'
  return currentPath.value.startsWith(path)
}

const navItems = computed(() => {
  const items = [
    { path: '/', labelKey: 'layout.nav.identity' },
    { path: '/market', labelKey: 'layout.nav.market' },
    { path: '/models', labelKey: 'layout.nav.models' },
  ]
  if (
    hasPermission('skill:contribute') ||
    hasPermission('mcp:contribute') ||
    hasPermission('agent:contribute')
  ) {
    items.push({ path: '/contributor', labelKey: 'layout.nav.contributor' })
  }
  return items
})

// 下拉菜单
const showDropdown = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLElement | null>(null)
const dropdownStyle = ref({ top: '0px', right: '0px' })

function toggleDropdown(): void {
  showDropdown.value = !showDropdown.value
  if (showDropdown.value) {
    nextTick(() => {
      updateDropdownPosition()
    })
  }
}

function updateDropdownPosition(): void {
  if (!triggerRef.value) return
  const rect = triggerRef.value.getBoundingClientRect()
  dropdownStyle.value = {
    top: `${rect.bottom + 4}px`,
    right: `${window.innerWidth - rect.right}px`,
  }
}
</script>

<template>
  <div class="relative flex min-h-screen flex-col overflow-hidden bg-slate-50">
    <!-- 顶部导航 -->
    <header class="relative z-30 grid h-[60px] grid-cols-3 items-center border-b border-slate-200/60 bg-white/70 px-6 backdrop-blur-xl">
      <!-- 左：Logo -->
      <div class="flex items-center">
        <RouterLink to="/" class="flex items-center gap-2.5">
          <div class="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-purple-600 to-blue-600 text-xs font-bold text-white shadow-md shadow-purple-500/20">
            AI
          </div>
          <span class="text-lg font-bold text-slate-900">AIHelms</span>
        </RouterLink>
      </div>

      <!-- 中：导航居中 -->
      <nav class="flex items-center justify-center gap-1">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path"
          class="whitespace-nowrap rounded-lg px-3.5 py-2 text-sm transition-colors"
          :class="isActive(item.path) ? 'bg-purple-50 font-medium text-purple-700' : 'text-slate-600 hover:bg-slate-100'">
          {{ t(item.labelKey) }}
        </RouterLink>
      </nav>

      <!-- 右：用户操作 -->
      <div class="flex items-center justify-end gap-3">
        <LanguageSwitcher />
        <RouterLink to="/my-keys"
          class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors"
          :class="isActive('/my-keys') ? 'bg-purple-50 font-medium text-purple-700' : 'text-slate-600 hover:bg-slate-100'">
          <KeyRound class="h-4 w-4" />
          {{ t('layout.apiKeys') }}
        </RouterLink>
        <a v-if="currentUser?.is_admin" href="/admin/"
          class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100">
          <Settings class="h-4 w-4" />
          {{ t('layout.adminConsole') }}
        </a>

        <!-- 用户下拉菜单 -->
        <div class="relative">
          <button ref="triggerRef" @click="toggleDropdown"
            class="flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100">
            <span>{{ currentUser?.display_name || currentUser?.email || currentUser?.username || '...' }}</span>
            <ChevronDown class="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </header>

    <!-- 内容区 -->
    <main class="relative z-10 flex-1 overflow-y-auto">
      <RouterView />
    </main>

    <!-- 下拉菜单（Teleport 到 body 避免 z-index 层叠问题） -->
    <Teleport to="body">
      <div v-if="showDropdown" ref="dropdownRef"
        class="fixed z-[9999] w-48 rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
        :style="dropdownStyle">
        <button @click="handleLogout"
          class="flex w-full items-center gap-2.5 px-4 py-2.5 text-sm text-red-500 hover:bg-slate-50">
          <LogOut class="h-4 w-4" />
          {{ t('layout.logout') }}
        </button>
      </div>
    </Teleport>
  </div>
</template>
