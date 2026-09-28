<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast, getContributionVersions, activateContributionVersion } from '@aihelms/shared'
import type { Skill, SkillVersion } from '@aihelms/shared'
import { X, CheckCircle2 } from 'lucide-vue-next'

interface Props {
  visible: boolean
  skill: Skill | null
}
const props = withDefaults(defineProps<Props>(), { skill: null })
const emit = defineEmits<{ close: []; activated: [] }>()

const { t } = useI18n()
const versions = ref<SkillVersion[]>([])
const loading = ref(false)
const actingId = ref<number | null>(null)

async function load(): Promise<void> {
  if (!props.skill) return
  loading.value = true
  try {
    versions.value = await getContributionVersions(props.skill.id)
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.visible,
  (v) => {
    if (v) void load()
  },
)

function canActivate(v: SkillVersion): boolean {
  return (
    versions.value.length > 1 &&
    !v.is_active &&
    (v.lifecycle_status === 'draft' || v.lifecycle_status === 'published')
  )
}

function statusLabel(v: SkillVersion): string {
  if (v.is_active) return t('contributor.version.statusActive')
  if (v.lifecycle_status === 'yanked') return t('contributor.version.statusYanked')
  if (v.lifecycle_status === 'deprecated') return t('contributor.version.statusDeprecated')
  return t('contributor.version.statusInactive')
}

async function handleActivate(v: SkillVersion): Promise<void> {
  if (!props.skill || actingId.value) return
  if (!window.confirm(t('contributor.version.activateConfirm', { version: v.version }))) return
  actingId.value = v.id
  try {
    await activateContributionVersion(props.skill.id, v.id)
    toast.success(t('contributor.version.msg.activated'))
    await load()
    emit('activated')
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    actingId.value = null
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[80] flex items-center justify-center bg-black/30" @click.self="emit('close')">
      <div class="max-h-[80vh] w-full max-w-xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-base font-semibold text-slate-800">
            {{ t('contributor.version.title', { name: skill?.name ?? '' }) }}
          </h3>
          <button class="rounded p-1 text-slate-400 hover:text-slate-600" @click="emit('close')"><X class="h-4 w-4" /></button>
        </div>
        <div v-if="loading" class="py-8 text-center text-sm text-slate-400">{{ t('contributor.version.loading') }}</div>
        <div v-else class="space-y-2">
          <div
            v-for="v in versions"
            :key="v.id"
            class="flex items-center justify-between rounded-lg border border-slate-200 px-4 py-3"
            :class="v.is_active ? 'border-green-200 bg-green-50/50' : ''"
          >
            <div class="min-w-0">
              <div class="flex items-center gap-2 text-sm font-medium text-slate-800">
                <span>v{{ v.version }}</span>
                <span v-if="v.is_active" class="flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700">
                  <CheckCircle2 class="h-3 w-3" />{{ t('contributor.version.statusActive') }}
                </span>
                <span v-else class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{{ statusLabel(v) }}</span>
              </div>
              <div v-if="v.change_log" class="mt-1 truncate text-xs text-slate-500">{{ v.change_log }}</div>
            </div>
            <button
              v-if="canActivate(v)"
              :disabled="actingId === v.id"
              class="shrink-0 rounded-lg bg-purple-600 px-3 py-1.5 text-xs text-white hover:bg-purple-700 disabled:opacity-50"
              @click="handleActivate(v)"
            >
              {{ actingId === v.id ? '...' : t('contributor.version.btn.activate') }}
            </button>
          </div>
        </div>
        <p class="mt-3 text-xs text-slate-400">{{ t('contributor.version.hint') }}</p>
      </div>
    </div>
  </Teleport>
</template>
