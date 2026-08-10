<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { Calendar, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-vue-next'

interface Props {
  modelValue?: string
  locale?: string
  max?: string
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  locale: 'zh-CN',
  max: '',
})
const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const PANEL_WIDTH = 224

const showPanel = ref(false)
const panelYear = ref(Number((props.modelValue || formatYM(new Date())).split('-')[0]))
const triggerRef = ref<HTMLElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const panelPos = ref<{ left: string; top: string }>({ left: '0px', top: '0px' })

function formatYM(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

const monthLabels = computed(() =>
  Array.from({ length: 12 }, (_, i) =>
    new Intl.DateTimeFormat(props.locale, { month: 'short' }).format(new Date(2000, i, 1))
  )
)
const selectedLabel = computed(() => {
  if (!props.modelValue) return '--'
  const [y, m] = props.modelValue.split('-').map(Number)
  return new Intl.DateTimeFormat(props.locale, { year: 'numeric', month: 'long' }).format(new Date(y, m - 1, 1))
})

function positionPanel(): void {
  const el = triggerRef.value
  if (!el) return
  const r = el.getBoundingClientRect()
  panelPos.value = { left: `${r.right - PANEL_WIDTH}px`, top: `${r.bottom + 4}px` }
}
async function togglePanel(): Promise<void> {
  showPanel.value = !showPanel.value
  if (showPanel.value) {
    if (props.modelValue) panelYear.value = Number(props.modelValue.split('-')[0])
    await nextTick()
    positionPanel()
  }
}
function isFuture(m: number): boolean {
  return props.max ? `${panelYear.value}-${String(m).padStart(2, '0')}` > props.max : false
}
function isSelected(m: number): boolean {
  if (!props.modelValue) return false
  const [y, mo] = props.modelValue.split('-').map(Number)
  return panelYear.value === y && m === mo
}
function pick(m: number): void {
  emit('update:modelValue', `${panelYear.value}-${String(m).padStart(2, '0')}`)
  showPanel.value = false
}
function onDocClick(e: MouseEvent): void {
  const t = e.target as Node
  if (triggerRef.value?.contains(t) || panelRef.value?.contains(t)) return
  showPanel.value = false
}
function onResize(): void {
  if (showPanel.value) positionPanel()
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="relative inline-block">
    <button ref="triggerRef" type="button" @click="togglePanel"
            class="flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50">
      <Calendar class="h-3.5 w-3.5 text-slate-400" />
      <span>{{ selectedLabel }}</span>
      <ChevronDown class="h-3.5 w-3.5 text-slate-400 transition-transform" :class="{ 'rotate-180': showPanel }" />
    </button>
    <Teleport to="body">
      <div v-if="showPanel" ref="panelRef" class="fixed z-50 w-56 rounded-xl border border-slate-200 bg-white p-3 shadow-lg"
           :style="panelPos">
        <div class="mb-2 flex items-center justify-between">
          <button type="button" @click="panelYear--"
                  class="flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100">
            <ChevronLeft class="h-4 w-4" />
          </button>
          <span class="text-sm font-medium text-slate-900">{{ panelYear }}</span>
          <button type="button" @click="panelYear++"
                  class="flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100">
            <ChevronRight class="h-4 w-4" />
          </button>
        </div>
        <div class="grid grid-cols-3 gap-1">
          <button v-for="(label, i) in monthLabels" :key="i" type="button"
                  :disabled="isFuture(i + 1)" @click="pick(i + 1)"
                  class="rounded-md py-1.5 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-30"
                  :class="isSelected(i + 1) ? 'bg-purple-500 font-medium text-white' : 'text-slate-600 hover:bg-slate-100'">
            {{ label }}
          </button>
        </div>
      </div>
    </Teleport>
  </div>
</template>
