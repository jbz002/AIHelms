import { ref, watch, toValue, type MaybeRefOrGetter } from 'vue'
import { useAuth, listLibraries } from '@aihelms/shared'
import type { DocumentLibrary } from '@aihelms/shared'

// 库级归属判定：「我的 / 可管理」= 当前用户是 admin 或该库 created_by。
// 路由化后各文档页（列表/详情/接口）都用 :libraryName，统一由此查库算 canManage。
export function useDocsOwner(libraryName: MaybeRefOrGetter<string | null | undefined>) {
  const { currentUser } = useAuth()
  const library = ref<DocumentLibrary | null>(null)
  const canManage = ref(false)

  async function load(): Promise<void> {
    const name = toValue(libraryName)
    if (!name) {
      library.value = null
      canManage.value = false
      return
    }
    try {
      const res = await listLibraries(1, 200)
      const lib = res.items.find((l) => l.name === name) ?? null
      library.value = lib
      const u = currentUser.value
      canManage.value = !!u && (!!u.is_admin || (lib?.created_by != null && lib.created_by === u.id))
    } catch {
      library.value = null
      canManage.value = false
    }
  }

  watch(() => toValue(libraryName), load, { immediate: true })

  return { library, canManage, load }
}
