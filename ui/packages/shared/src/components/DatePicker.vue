<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { Calendar, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-vue-next'

interface Props {
  modelValue?: string
  locale?: string
  min?: string
  max?: string
  placeholder?: string
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  locale: 'zh-CN',
  min: '',
  max: '',
  placeholder: '—',
})
const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const PANEL_WIDTH = 256

function parse(value: string): { y: number; m: number; d: number } {
  const [y, m, d] = (value || formatYMD(new Date())).split('-').map(Number)
  return { y, m: m - 1, d }
}
function formatYMD(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function pad(n: number): string {
  return String(n).padStart(2, '0')
}

const init = parse(props.modelValue)
const viewYear = ref(init.y)
const viewMonth = ref(init.m)
const showPanel = ref(false)
const triggerRef = ref<HTMLElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const panelPos = ref<{ left: string; top: string }>({ left: '0px', top: '0px' })

const monthTitle = computed(() =>
  new Intl.DateTimeFormat(props.locale, { year: 'numeric', month: 'long' }).format(new Date(viewYear.value, viewMonth.value, 1))
)
const selectedLabel = computed(() => {
  if (!props.modelValue) return props.placeholder
  const { y, m, d } = parse(props.modelValue)
  return new Intl.DateTimeFormat(props.locale, { year: 'numeric', month: 'long', day: 'numeric' }).format(new Date(y, m, d))
})
const weekdayLabels = computed(() => {
  // 2024-01-01 是周一,取其后 7 天生成 周一~周日 表头
  return Array.from({ length: 7 }, (_, i) =>
    new Intl.DateTimeFormat(props.locale, { weekday: 'narrow' }).format(new Date(2024, 0, 1 + i))
  )
})
const gridDays = computed(() => {
  const firstDay = new Date(viewYear.value, viewMonth.value, 1).getDay()
  const leading = (firstDay + 6) % 7
  const daysInMonth = new Date(viewYear.value, viewMonth.value + 1, 0).getDate()
  const cells: (number | null)[] = []
  for (let i = 0; i < leading; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) cells.push(d)
  return cells
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
    if (props.modelValue) {
      const { y, m } = parse(props.modelValue)
      viewYear.value = y
      viewMonth.value = m
    }
    await nextTick()
    positionPanel()
  }
}
function prevMonth(): void {
  if (viewMonth.value === 0) { viewMonth.value = 11; viewYear.value-- }
  else viewMonth.value--
}
function nextMonth(): void {
  if (viewMonth.value === 11) { viewMonth.value = 0; viewYear.value++ }
  else viewMonth.value++
}
function isDisabled(d: number): boolean {
  const ds = `${viewYear.value}-${pad(viewMonth.value + 1)}-${pad(d)}`
  if (props.min && ds < props.min) return true
  if (props.max && ds > props.max) return true
  return false
}
function isSelected(d: number): boolean {
  if (!props.modelValue) return false
  const ds = `${viewYear.value}-${pad(viewMonth.value + 1)}-${pad(d)}`
  return props.modelValue === ds
}
function isToday(d: number): boolean {
  const t = new Date()
  return viewYear.value === t.getFullYear() && viewMonth.value === t.getMonth() && d === t.getDate()
}
function pick(d: number): void {
  emit('update:modelValue', `${viewYear.value}-${pad(viewMonth.value + 1)}-${pad(d)}`)
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
      <div v-if="showPanel" ref="panelRef" class="fixed z-50 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-lg"
           :style="panelPos">
        <div class="mb-2 flex items-center justify-between">
          <button type="button" @click="prevMonth"
                  class="flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100">
            <ChevronLeft class="h-4 w-4" />
          </button>
          <span class="text-sm font-medium text-slate-900">{{ monthTitle }}</span>
          <button type="button" @click="nextMonth"
                  class="flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100">
            <ChevronRight class="h-4 w-4" />
          </button>
        </div>
        <div class="mb-1 grid grid-cols-7 gap-0.5 text-center">
          <span v-for="(w, i) in weekdayLabels" :key="i" class="py-1 text-xs text-slate-400">{{ w }}</span>
        </div>
        <div class="grid grid-cols-7 gap-0.5">
          <template v-for="(d, i) in gridDays" :key="i">
            <span v-if="d === null" />
            <button v-else type="button" :disabled="isDisabled(d)" @click="pick(d)"
                    class="rounded-md py-1.5 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-30"
                    :class="isSelected(d)
                      ? 'bg-purple-500 font-medium text-white'
                      : isToday(d) ? 'text-slate-900 ring-1 ring-purple-300 hover:bg-slate-100' : 'text-slate-600 hover:bg-slate-100'">
              {{ d }}
            </button>
          </template>
        </div>
      </div>
    </Teleport>
  </div>
</template>
