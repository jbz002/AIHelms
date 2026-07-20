<script setup lang="ts">
import { computed, ref } from 'vue'
import { Star } from 'lucide-vue-next'

type Size = 'sm' | 'md' | 'lg'

interface Props {
  modelValue?: number
  readonlyValue?: number
  readonly?: boolean
  size?: Size
  count?: number
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: 0,
  readonlyValue: 0,
  readonly: false,
  size: 'md',
  count: undefined,
})

const emit = defineEmits<{ 'update:modelValue': [value: number] }>()

const SIZE_PX: Record<Size, number> = { sm: 14, md: 20, lg: 28 }
const GAP_PX: Record<Size, number> = { sm: 1, md: 2, lg: 3 }

const hoverValue = ref(0)
const isInteractive = computed(() => !props.readonly)

const displayValue = computed(() => {
  if (props.readonly) return props.readonlyValue
  return hoverValue.value || props.modelValue
})

const starSize = computed(() => SIZE_PX[props.size])
const gap = computed(() => GAP_PX[props.size])
const fillPercent = computed(() => `${(Math.max(0, Math.min(5, displayValue.value)) / 5) * 100}%`)
const rowWidth = computed(() => `${starSize.value * 5 + gap.value * 4}px`)

function handleClick(star: number) {
  if (!isInteractive.value) return
  emit('update:modelValue', star)
}
</script>

<template>
  <div class="flex items-center" :style="{ gap: gap + 'px' }">
    <div class="relative select-none" :style="{ width: rowWidth, height: starSize + 'px' }">
      <div class="flex" :style="{ gap: gap + 'px' }">
        <Star
          v-for="star in 5"
          :key="star"
          :size="starSize"
          :fill="isInteractive && star <= displayValue ? 'currentColor' : 'none'"
          stroke-width="1.5"
          class="text-slate-300"
          :class="isInteractive ? 'cursor-pointer' : ''"
          @click="handleClick(star)"
          @mouseenter="isInteractive ? (hoverValue = star) : undefined"
          @mouseleave="isInteractive ? (hoverValue = 0) : undefined"
        />
      </div>
      <div
        v-if="displayValue > 0"
        class="absolute inset-0 overflow-hidden"
        :style="{ width: fillPercent }"
      >
        <div class="flex" :style="{ gap: gap + 'px' }">
          <Star
            v-for="star in 5"
            :key="star"
            :size="starSize"
            fill="currentColor"
            stroke-width="1.5"
            class="text-amber-400"
            :class="isInteractive ? 'cursor-pointer' : ''"
            @click="handleClick(star)"
            @mouseenter="isInteractive ? (hoverValue = star) : undefined"
            @mouseleave="isInteractive ? (hoverValue = 0) : undefined"
          />
        </div>
      </div>
    </div>
    <span v-if="readonly && count !== undefined" class="text-slate-500" :style="{ fontSize: starSize * 0.8 + 'px' }">
      {{ readonlyValue.toFixed(1) }} ({{ count }})
    </span>
  </div>
</template>
