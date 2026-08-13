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

function splitValue(value: string): { dateStr: string; time: string } {
  const [datePart, timePart] = (value || '').split('T')
  return { dateStr: datePart || '', time: (timePart || '00:00').slice(0, 5) }
}
function parseYMD(value: string): { y: number; m: number; d: number } {
  const fallback = formatYMD(new Date())
  const [y, m, d] = (value || fallback).split('-').map(Number)
  return { y, m: (m || 1) - 1, d: d || 1 }
}
function formatYMD(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function pad(n: number): string {
  return String(n).padStart(2, '0')
}

const init = splitValue(props.modelValue)
const selectedYMD = ref(init.dateStr)
const time = ref(init.time)
const viewYear = ref(parseYMD(init.dateStr).y)
const viewMonth = ref(parseYMD(init.dateStr).m)
const showPanel = ref(false)
const triggerRef = ref<HTMLElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const panelPos = ref<{ left: string; top: string }>({ left: '0px', top: '0px' })

const monthTitle = computed(() =>
  new Intl.DateTimeFormat(props.locale, { year: 'numeric', month: 'long' }).format(new Date(viewYear.value, viewMonth.value, 1))
)
const selectedLabel = computed(() => {
  if (!props.modelValue) return props.placeholder
  const { dateStr, time: t } = splitValue(props.modelValue)
  if (!dateStr) return props.placeholder
  const { y, m, d } = parseYMD(dateStr)
  return `${y}-${pad(m + 1)}-${pad(d)} ${t}`
})
const weekdayLabels = computed(() =>
  Array.from({ length: 7 }, (_, i) =>
    new Intl.DateTimeFormat(props.locale, { weekday: 'narrow' }).format(new Date(2024, 0, 1 + i))
  )
)
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
      const { dateStr, time: t } = splitValue(props.modelValue)
      const { y, m } = parseYMD(dateStr)
      selectedYMD.value = dateStr
      time.value = t
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
  const minD = props.min ? props.min.split('T')[0] : ''
  const maxD = props.max ? props.max.split('T')[0] : ''
  if (minD && ds < minD) return true
  if (maxD && ds > maxD) return true
  return false
}
function isSelected(d: number): boolean {
  if (!selectedYMD.value) return false
  const ds = `${viewYear.value}-${pad(viewMonth.value + 1)}-${pad(d)}`
  return selectedYMD.value === ds
}
function isToday(d: number): boolean {
  const t = new Date()
  return viewYear.value === t.getFullYear() && viewMonth.value === t.getMonth() && d === t.getDate()
}
const hh = computed(() => Number(time.value.split(':')[0]) || 0)
const mm = computed(() => Number(time.value.split(':')[1]) || 0)

function emitValue(): void {
  if (!selectedYMD.value) return
  emit('update:modelValue', `${selectedYMD.value}T${time.value}`)
}
function pick(d: number): void {
  selectedYMD.value = `${viewYear.value}-${pad(viewMonth.value + 1)}-${pad(d)}`
  emitValue()
}
function stepHour(delta: number): void {
  const next = (hh.value + delta + 24) % 24
  time.value = `${pad(next)}:${pad(mm.value)}`
  emitValue()
}
function stepMinute(delta: number): void {
  const next = (mm.value + delta + 60) % 60
  time.value = `${pad(hh.value)}:${pad(next)}`
  emitValue()
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
  <div class="relative">
    <button
      ref="triggerRef"
      type="button"
      class="flex h-9 w-full items-center rounded-lg border border-slate-200 bg-white text-sm transition-colors focus:border-purple-500 focus:outline-none"
      @click="togglePanel"
    >
      <span class="flex flex-1 items-center gap-1.5 px-3 text-left" :class="!modelValue ? 'text-slate-500' : 'text-slate-700'">
        <Calendar class="-translate-y-px h-4 w-4 shrink-0 text-slate-400" />
        <span class="truncate">{{ selectedLabel }}</span>
      </span>
      <ChevronDown class="mr-2 h-4 w-4 shrink-0 text-slate-400 transition-transform" :class="{ 'rotate-180': showPanel }" />
    </button>
    <Teleport to="body">
      <div
        v-if="showPanel"
        ref="panelRef"
        class="fixed z-50 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-lg"
        :style="panelPos"
      >
        <div class="mb-2 flex items-center justify-between">
          <button
            type="button"
            class="flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
            @click="prevMonth"
          >
            <ChevronLeft class="h-4 w-4" />
          </button>
          <span class="text-sm font-medium text-slate-900">{{ monthTitle }}</span>
          <button
            type="button"
            class="flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
            @click="nextMonth"
          >
            <ChevronRight class="h-4 w-4" />
          </button>
        </div>
        <div class="mb-1 grid grid-cols-7 gap-0.5 text-center">
          <span v-for="(w, i) in weekdayLabels" :key="i" class="py-1 text-xs text-slate-400">{{ w }}</span>
        </div>
        <div class="grid grid-cols-7 gap-0.5">
          <template v-for="(d, i) in gridDays" :key="i">
            <span v-if="d === null" />
            <button
              v-else
              type="button"
              :disabled="isDisabled(d)"
              class="rounded-md py-1.5 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-30"
              :class="isSelected(d)
                ? 'bg-purple-500 font-medium text-white'
                : isToday(d) ? 'text-slate-900 ring-1 ring-purple-300 hover:bg-slate-100' : 'text-slate-600 hover:bg-slate-100'"
              @click="pick(d)"
            >
              {{ d }}
            </button>
          </template>
        </div>
        <div class="mt-2 flex items-center justify-around gap-2 border-t border-slate-100 pt-2">
          <div class="flex items-center gap-1">
            <span class="text-xs text-slate-500">时</span>
            <button
              type="button"
              class="flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
              @click="stepHour(-1)"
            >
              <ChevronLeft class="h-4 w-4" />
            </button>
            <span class="w-7 text-center text-sm font-medium tabular-nums text-slate-900">{{ pad(hh) }}</span>
            <button
              type="button"
              class="flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
              @click="stepHour(1)"
            >
              <ChevronRight class="h-4 w-4" />
            </button>
          </div>
          <div class="flex items-center gap-1">
            <span class="text-xs text-slate-500">分</span>
            <button
              type="button"
              class="flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
              @click="stepMinute(-5)"
            >
              <ChevronLeft class="h-4 w-4" />
            </button>
            <span class="w-7 text-center text-sm font-medium tabular-nums text-slate-900">{{ pad(mm) }}</span>
            <button
              type="button"
              class="flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
              @click="stepMinute(5)"
            >
              <ChevronRight class="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
