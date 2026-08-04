<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconPicker, toast, createContribution, updateContribution, createContributionVersion, getSkillCategories } from '@aihelms/shared'
import type { Skill, SkillCategory } from '@aihelms/shared'
import { X } from 'lucide-vue-next'

type FormMode = 'create' | 'edit' | 'version'

interface Props {
  visible: boolean
  mode: FormMode
  skill?: Skill | null
}
const props = withDefaults(defineProps<Props>(), { skill: null })
const emit = defineEmits<{ close: []; saved: [] }>()

const { t } = useI18n()
const MAX_ZIP_SIZE = 100 * 1024 * 1024

const name = ref('')
const iconUrl = ref('')
const description = ref('')
const author = ref('')
const category = ref('general')
const categoryList = ref<SkillCategory[]>([])
const version = ref('1.0.0')
const tagsText = ref('')
const usage = ref('')
const changeLog = ref('')
const sourceMode = ref<'zip' | 'url'>('zip')
const zipFile = ref<File | null>(null)
const sourceUrl = ref('')
const saving = ref(false)

const isVersion = computed(() => props.mode === 'version')
const titleKey = computed(() =>
  isVersion.value
    ? 'contributor.skill.title.version'
    : props.mode === 'edit'
      ? 'contributor.skill.title.edit'
      : 'contributor.skill.title.create',
)

watch(
  () => props.visible,
  (v) => {
    if (!v) return
    if (props.mode === 'edit' && props.skill) {
      name.value = props.skill.name
      iconUrl.value = props.skill.icon_url ?? ''
      description.value = props.skill.description ?? ''
      author.value = props.skill.author ?? ''
      category.value = props.skill.category ?? 'general'
      version.value = props.skill.version ?? '1.0.0'
      tagsText.value = (props.skill.tags ?? []).join(', ')
      usage.value = props.skill.usage_instructions ?? ''
    } else if (props.mode === 'version' && props.skill) {
      version.value = bumpVersion(props.skill.version)
      changeLog.value = ''
      zipFile.value = null
    } else {
      resetCreate()
    }
    void loadCategories()
  },
)

function resetCreate(): void {
  name.value = ''
  iconUrl.value = ''
  description.value = ''
  author.value = ''
  category.value = 'general'
  version.value = '1.0.0'
  tagsText.value = ''
  usage.value = ''
  sourceMode.value = 'zip'
  zipFile.value = null
  sourceUrl.value = ''
}

async function loadCategories(): Promise<void> {
  try {
    categoryList.value = await getSkillCategories()
  } catch {
    categoryList.value = []
  }
  const names = categoryList.value.map((c) => c.name)
  if (names.length && category.value === 'general' && props.mode === 'create') {
    category.value = names[0]
  }
}

const categoryOptions = computed(() => {
  const names = categoryList.value.map((c) => c.name)
  if (!category.value || names.includes(category.value)) return names
  return [category.value, ...names]
})

function bumpVersion(v: string): string {
  const parts = v.split('.').map((n) => Number.parseInt(n, 10))
  if (parts.length === 3 && parts.every((n) => !Number.isNaN(n))) {
    parts[2] += 1
    return parts.join('.')
  }
  return v
}

function handleZipChange(e: Event): void {
  const target = e.target as HTMLInputElement
  zipFile.value = target.files && target.files[0] ? target.files[0] : null
}

function validate(): string | null {
  if (isVersion.value) {
    if (!version.value.trim()) return t('contributor.skill.msg.versionRequired')
    return null
  }
  if (!name.value.trim()) return t('contributor.skill.msg.nameRequired')
  if (props.mode === 'create') {
    if (sourceMode.value === 'zip' && !zipFile.value) return t('contributor.skill.msg.sourceRequired')
    if (sourceMode.value === 'url' && !sourceUrl.value.trim()) return t('contributor.skill.msg.sourceRequired')
  }
  if (zipFile.value && zipFile.value.size > MAX_ZIP_SIZE) return t('contributor.skill.msg.zipTooLarge')
  return null
}

async function handleSubmit(): Promise<void> {
  const err = validate()
  if (err) {
    toast.error(err)
    return
  }
  saving.value = true
  try {
    if (isVersion.value && props.skill) {
      await createContributionVersion(props.skill.id, {
        version: version.value.trim(),
        change_log: changeLog.value,
        zip_file: zipFile.value,
      })
    } else if (props.mode === 'edit' && props.skill) {
      await updateContribution(props.skill.id, {
        name: name.value.trim(),
        icon_url: iconUrl.value,
        description: description.value,
        author: author.value,
        category: category.value,
        version: version.value.trim(),
        tags: tagsText.value.split(',').map((s) => s.trim()).filter(Boolean),
        usage_instructions: usage.value,
      })
    } else {
      await createContribution({
        name: name.value.trim(),
        icon_url: iconUrl.value,
        description: description.value,
        author: author.value,
        category: category.value,
        version: version.value.trim(),
        tags: tagsText.value.split(',').map((s) => s.trim()).filter(Boolean),
        usage_instructions: usage.value,
        visibility_type: 'all',
        zip_file: sourceMode.value === 'zip' ? zipFile.value : null,
        source_url: sourceMode.value === 'url' ? sourceUrl.value.trim() : '',
      })
    }
    emit('saved')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[80] flex items-center justify-center bg-black/30" @click.self="emit('close')">
      <div class="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-base font-semibold text-slate-800">{{ t(titleKey) }}</h3>
          <button class="rounded p-1 text-slate-400 hover:text-slate-600" @click="emit('close')"><X class="h-4 w-4" /></button>
        </div>
        <div class="space-y-3">
          <div v-if="!isVersion" class="flex items-center gap-3">
            <IconPicker v-model="iconUrl" :label="t('contributor.skill.field.icon')" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.skill.field.name') }}</label>
            <input v-model="name" type="text" :placeholder="t('contributor.skill.placeholder.name')" :disabled="isVersion"
              class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none disabled:bg-slate-50" />
          </div>
          <div v-if="!isVersion" class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.skill.field.author') }}</label>
              <input v-model="author" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.skill.field.category') }}</label>
              <select v-if="categoryList.length" v-model="category" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none">
                <option v-for="c in categoryOptions" :key="c" :value="c">{{ c }}</option>
              </select>
              <input v-else v-model="category" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.skill.field.version') }}</label>
            <input v-model="version" type="text" :placeholder="t('contributor.skill.placeholder.version')"
              class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
          </div>
          <div v-if="isVersion">
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.skill.field.changeLog') }}</label>
            <textarea v-model="changeLog" rows="2" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
          </div>
          <div v-if="!isVersion">
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.skill.field.description') }}</label>
            <textarea v-model="description" rows="2" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
          </div>
          <div v-if="!isVersion">
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.skill.field.tags') }}</label>
            <input v-model="tagsText" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
          </div>
          <div v-if="!isVersion">
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.skill.field.usage') }}</label>
            <textarea v-model="usage" rows="2" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
          </div>
          <div v-if="isVersion || mode === 'create'">
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.skill.field.source') }}</label>
            <div v-if="mode === 'create'" class="mb-2 flex gap-3 text-sm">
              <label class="flex items-center gap-1"><input v-model="sourceMode" type="radio" value="zip" /> {{ t('contributor.skill.source.zip') }}</label>
              <label class="flex items-center gap-1"><input v-model="sourceMode" type="radio" value="url" /> {{ t('contributor.skill.source.url') }}</label>
            </div>
            <input v-if="sourceMode === 'zip' || isVersion" type="file" accept=".zip" :placeholder="t('contributor.skill.placeholder.zip')"
              @change="handleZipChange" class="w-full text-sm text-slate-600 file:mr-3 file:rounded file:border-0 file:bg-purple-50 file:px-3 file:py-1.5 file:text-purple-700" />
            <input v-else v-model="sourceUrl" type="text" :placeholder="t('contributor.skill.placeholder.url')"
              class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
          </div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button class="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100" @click="emit('close')">{{ t('contributor.skill.btn.cancel') }}</button>
          <button :disabled="saving" class="rounded-lg bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-700 disabled:opacity-50" @click="handleSubmit">{{ t('contributor.skill.btn.save') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
