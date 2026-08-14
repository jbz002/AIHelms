<script setup lang="ts">
import { computed } from 'vue'
import HostedIcon from '@aihelms/shared/src/components/HostedIcon.vue'
import { getProviderIconUrl, hasProviderIcon } from '@aihelms/shared'

interface Props {
  type?: string
  src?: string
  size?: number
}

const props = withDefaults(defineProps<Props>(), { type: '', src: '', size: 24 })

const iconSrc = computed(() => {
  if (props.src) return props.src
  return getProviderIconUrl(props.type)
})

// 无内置图标（registry 动态 provider 多数无图标）→ 渲染确定性首字母占位
const useLetter = computed(() => !props.src && !!props.type && !hasProviderIcon(props.type))
const letter = computed(() => (props.type || '?').trim().charAt(0).toUpperCase() || '?')
const bgColor = computed(() => {
  let h = 0
  for (const ch of props.type || '?') h = (h * 31 + ch.charCodeAt(0)) % 360
  return `hsl(${h} 55% 45%)`
})
</script>

<template>
  <div
    v-if="useLetter"
    class="flex shrink-0 items-center justify-center rounded-full font-semibold text-white"
    :style="{ width: `${size}px`, height: `${size}px`, fontSize: `${Math.round(size * 0.5)}px`, backgroundColor: bgColor }"
  >{{ letter }}</div>
  <HostedIcon
    v-else
    :src="iconSrc"
    :alt="type"
    :size="size"
  />
</template>
