import { ref, computed, watch, toValue, type MaybeRefOrGetter } from 'vue'
import { useAuth, listLibraries } from '@aihelms/shared'
import type { DocumentLibrary } from '@aihelms/shared'

// 库级归属判定：「我的 / 可管理」= 当前用户是 admin 或该库 created_by。
// 路由化后各文档页（列表/详情/接口）都用 :libraryName，统一由此查库算 canManage。
export function useDocsOwner(libraryName: MaybeRefOrGetter<string | null | undefined>) {
  const { currentUser } = useAuth()
  const library = ref<DocumentLibrary | null>(null)

  // 用 computed 而非 ref：currentUser 异步加载完成、library 查询返回后都要重算，
  // 否则首次 load() 跑在 currentUser 就绪前会把 canManage 永久卡在 false。
  const canManage = computed(() => {
    const u = currentUser.value
    const lib = library.value
    return !!u && (!!u.is_admin || (lib?.created_by != null && lib.created_by === u.id))
  })

  async function load(): Promise<void> {
    const name = toValue(libraryName)
    if (!name) {
      library.value = null
      return
    }
    try {
      // page_size 上限 100（后端 Query le=100），超过会 422 导致 library 永远为空
      const res = await listLibraries(1, 100)
      library.value = res.items.find((l) => l.name === name) ?? null
    } catch {
      library.value = null
    }
  }

  watch(() => toValue(libraryName), load, { immediate: true })

  return { library, canManage, load }
}
