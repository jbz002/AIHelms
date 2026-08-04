<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconPicker, toast, createAgentContribution, updateAgentContribution, getAgentCategories } from '@aihelms/shared'
import type { Agent, AgentCategory } from '@aihelms/shared'
import { X } from 'lucide-vue-next'

type FormMode = 'create' | 'edit'

interface Props {
  visible: boolean
  mode: FormMode
  agent?: Agent | null
}
const props = withDefaults(defineProps<Props>(), { agent: null })
const emit = defineEmits<{ close: []; saved: [] }>()

const { t } = useI18n()

const name = ref('')
const iconUrl = ref('')
const description = ref('')
const platform = ref('')
const category = ref('general')
const categoryList = ref<AgentCategory[]>([])
const chatUrl = ref('')
const tagsText = ref('')
const saving = ref(false)

const titleKey = computed(() =>
  props.mode === 'edit' ? 'contributor.agent.title.edit' : 'contributor.agent.title.create',
)

watch(
  () => props.visible,
  (v) => {
    if (!v) return
    if (props.mode === 'edit' && props.agent) {
      name.value = props.agent.name
      iconUrl.value = props.agent.icon_url ?? ''
      description.value = props.agent.description ?? ''
      platform.value = props.agent.platform ?? ''
      category.value = props.agent.category ?? 'general'
      chatUrl.value = props.agent.chat_url ?? ''
      tagsText.value = (props.agent.tags ?? []).join(', ')
    } else {
      name.value = ''
      iconUrl.value = ''
      description.value = ''
      platform.value = ''
      category.value = 'general'
      chatUrl.value = ''
      tagsText.value = ''
    }
    void loadCategories()
  },
)

async function loadCategories(): Promise<void> {
  try {
    categoryList.value = await getAgentCategories()
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

function validate(): string | null {
  if (!name.value.trim()) return t('contributor.agent.msg.nameRequired')
  if (!platform.value.trim()) return t('contributor.agent.msg.platformRequired')
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
    const fields = {
      name: name.value.trim(),
      icon_url: iconUrl.value,
      description: description.value,
      platform: platform.value.trim(),
      category: category.value,
      chat_url: chatUrl.value,
      tags: tagsText.value.split(',').map((s) => s.trim()).filter(Boolean),
    }
    if (props.mode === 'edit' && props.agent) {
      await updateAgentContribution(props.agent.id, fields)
    } else {
      await createAgentContribution(fields)
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
          <div class="flex items-center gap-3">
            <IconPicker v-model="iconUrl" :label="t('contributor.agent.field.icon')" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.agent.field.name') }}</label>
            <input v-model="name" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.agent.field.platform') }}</label>
              <input v-model="platform" type="text" :placeholder="t('contributor.agent.placeholder.platform')" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.agent.field.category') }}</label>
              <select v-if="categoryList.length" v-model="category" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none">
                <option v-for="c in categoryOptions" :key="c" :value="c">{{ c }}</option>
              </select>
              <input v-else v-model="category" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.agent.field.chatUrl') }}</label>
            <input v-model="chatUrl" type="text" :placeholder="t('contributor.agent.placeholder.chatUrl')" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.agent.field.description') }}</label>
            <textarea v-model="description" rows="2" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.agent.field.tags') }}</label>
            <input v-model="tagsText" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
          </div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button class="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100" @click="emit('close')">{{ t('contributor.agent.btn.cancel') }}</button>
          <button :disabled="saving" class="rounded-lg bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-700 disabled:opacity-50" @click="handleSubmit">{{ t('contributor.agent.btn.save') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
