import { ref } from 'vue'
import { login as apiLogin, loginOAuth2, getMe } from '../api/auth'
import type { CurrentUser } from '../types/auth'
import { getLoginUrl } from '../utils/auth-redirect'

const TOKEN_KEY = 'aihelms_token'
const currentUser = ref<CurrentUser | null>(null)
const isAuthenticated = ref(!!localStorage.getItem(TOKEN_KEY))

export function useAuth() {
  async function login(username: string, password: string): Promise<void> {
    const data = await apiLogin(username, password)
    localStorage.setItem(TOKEN_KEY, data.access_token)
    isAuthenticated.value = true
    await fetchCurrentUser()
  }

  async function loginWithCode(code: string): Promise<void> {
    const data = await loginOAuth2(code)
    localStorage.setItem(TOKEN_KEY, data.access_token)
    isAuthenticated.value = true
    await fetchCurrentUser()
  }

  function redirectToAiHub(aiHubUrl: string, appCode: string, callbackPath: string): void {
    const redirectUri = encodeURIComponent(`${window.location.origin}${callbackPath}`)
    window.location.href = `${aiHubUrl.replace(/\/$/, '')}/api/v1/auth/authorize?redirect_uri=${redirectUri}&app_code=${appCode}`
  }

  function logout(): void {
    localStorage.removeItem(TOKEN_KEY)
    isAuthenticated.value = false
    currentUser.value = null
    window.location.href = getLoginUrl()
  }

  async function fetchCurrentUser(): Promise<CurrentUser | null> {
    try {
      const user = await getMe()
      currentUser.value = user
      return user
    } catch {
      logout()
      return null
    }
  }

  function getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY)
  }

  return {
    currentUser,
    isAuthenticated,
    login,
    loginWithCode,
    redirectToAiHub,
    logout,
    fetchCurrentUser,
    getToken,
  }
}
