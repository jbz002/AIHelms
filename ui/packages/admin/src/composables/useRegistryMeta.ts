/**
 * registry 元数据单例 composable。
 *
 * 拉一次 GET /models/registry-meta（provider/mode/capability 全集），模块级缓存，
 * 所有调用方共享同一份 ref；并发调用去重为同一个 promise。
 * 驱动供应商下拉、能力候选、mode 候选，取代前端写死枚举。
 */
import { computed, ref } from 'vue'
import {
  registryMeta,
  type RegistryMeta,
  type RegistryProviderItem,
  type RegistryModeItem,
  type RegistryCapabilityItem,
} from '@aihelms/shared'

const meta = ref<RegistryMeta | null>(null)
const loading = ref(false)
let inflight: Promise<void> | null = null

async function load(): Promise<void> {
  if (meta.value || inflight) return inflight ?? Promise.resolve()
  loading.value = true
  inflight = registryMeta()
    .then((data) => {
      meta.value = data
    })
    .catch((e) => {
      // 失败不阻断页面：调用方各自降级到空候选
      console.error('[useRegistryMeta] 加载注册表元数据失败', e)
    })
    .finally(() => {
      loading.value = false
      inflight = null
    })
  return inflight
}

const providerOptions = computed<RegistryProviderItem[]>(() => meta.value?.providers ?? [])
const modeOptions = computed<RegistryModeItem[]>(() => meta.value?.modes ?? [])
const capabilityOptions = computed<RegistryCapabilityItem[]>(() => meta.value?.capabilities ?? [])

export function useRegistryMeta() {
  void load()
  return { meta, loading, providerOptions, modeOptions, capabilityOptions, refresh: load }
}
