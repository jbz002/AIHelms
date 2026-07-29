<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconPicker, toast, createMcpContribution, updateMcpContribution, createMcpContributionVersion } from '@aihelms/shared'
import type { McpServer } from '@aihelms/shared'
import { X } from 'lucide-vue-next'

type FormMode = 'create' | 'edit' | 'version'

interface Props {
  visible: boolean
  mode: FormMode
  server?: McpServer | null
}
const props = withDefaults(defineProps<Props>(), { server: null })
const emit = defineEmits<{ close: []; saved: [] }>()

const { t } = useI18n()

const name = ref('')
const serverName = ref('')
const url = ref('')
const transport = ref('sse')
const description = ref('')
const instructions = ref('')
const category = ref('general')
const tagsText = ref('')
const author = ref('')
const iconUrl = ref('')
const documentationUrl = ref('')
const sourceUrl = ref('')
const version = ref('1.0.1')
const changeLog = ref('')
const saving = ref(false)

const isVersion = computed(() => props.mode === 'version')
const titleKey = computed(() =>
  isVersion.value
    ? 'contributor.mcp.title.version'
    : props.mode === 'edit'
      ? 'contributor.mcp.title.edit'
      : 'contributor.mcp.title.create',
)

watch(
  () => props.visible,
  (v) => {
    if (!v) return
    if (isVersion.value && props.server) {
      version.value = bumpVersion(props.server.active_version?.version ?? '1.0.0')
      url.value = props.server.url ?? ''
      transport.value = props.server.transport ?? 'sse'
      changeLog.value = ''
    } else if (props.mode === 'edit' && props.server) {
      name.value = props.server.name
      serverName.value = props.server.server_name
      url.value = props.server.url
      transport.value = props.server.transport
      description.value = props.server.description ?? ''
      instructions.value = props.server.instructions ?? ''
      category.value = props.server.category ?? 'general'
      tagsText.value = (props.server.tags ?? []).join(', ')
      author.value = props.server.author ?? ''
      iconUrl.value = props.server.icon_url ?? ''
      documentationUrl.value = props.server.documentation_url ?? ''
      sourceUrl.value = props.server.source_url ?? ''
    } else {
      resetCreate()
    }
  },
)

function resetCreate(): void {
  name.value = ''
  serverName.value = ''
  url.value = ''
  transport.value = 'sse'
  description.value = ''
  instructions.value = ''
  category.value = 'general'
  tagsText.value = ''
  author.value = ''
  iconUrl.value = ''
  documentationUrl.value = ''
  sourceUrl.value = ''
}

function bumpVersion(v: string): string {
  const parts = v.split('.').map((n) => Number.parseInt(n, 10))
  if (parts.length === 3 && parts.every((n) => !Number.isNaN(n))) {
    parts[2] += 1
    return parts.join('.')
  }
  return v
}

function validate(): string | null {
  if (isVersion.value) {
    if (!version.value.trim()) return t('contributor.mcp.msg.versionRequired')
    if (!/^https?:\/\//.test(url.value.trim())) return t('contributor.mcp.msg.urlRequired')
    return null
  }
  if (!name.value.trim()) return t('contributor.mcp.msg.nameRequired')
  if (!/^[A-Za-z0-9_]+$/.test(serverName.value.trim())) return t('contributor.mcp.msg.serverNameRequired')
  if (!/^https?:\/\//.test(url.value.trim())) return t('contributor.mcp.msg.urlRequired')
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
    if (isVersion.value && props.server) {
      await createMcpContributionVersion(props.server.id, {
        version: version.value.trim(),
        url: url.value.trim(),
        transport: transport.value,
        change_log: changeLog.value,
      })
    } else if (props.mode === 'edit' && props.server) {
      await updateMcpContribution(props.server.id, {
        name: name.value.trim(),
        server_name: serverName.value.trim(),
        description: description.value,
        instructions: instructions.value,
        category: category.value,
        tags: tagsText.value.split(',').map((s) => s.trim()).filter(Boolean),
        author: author.value,
        icon_url: iconUrl.value,
        documentation_url: documentationUrl.value,
        source_url: sourceUrl.value,
      })
    } else {
      await createMcpContribution({
        name: name.value.trim(),
        server_name: serverName.value.trim(),
        url: url.value.trim(),
        transport: transport.value,
        description: description.value,
        instructions: instructions.value,
        category: category.value,
        tags: tagsText.value.split(',').map((s) => s.trim()).filter(Boolean),
        author: author.value,
        icon_url: iconUrl.value,
        documentation_url: documentationUrl.value,
        source_url: sourceUrl.value,
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
          <template v-if="isVersion">
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.version') }}</label>
              <input v-model="version" type="text" :placeholder="t('contributor.mcp.placeholder.version')" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.url') }}</label>
              <input v-model="url" type="text" :placeholder="t('contributor.mcp.placeholder.url')" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.transport') }}</label>
              <select v-model="transport" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none">
                <option value="sse">{{ t('contributor.mcp.transport.sse') }}</option>
                <option value="streamable_http">{{ t('contributor.mcp.transport.streamable') }}</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.changeLog') }}</label>
              <textarea v-model="changeLog" rows="2" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
          </template>
          <template v-else>
            <div class="flex items-center gap-3">
              <IconPicker v-model="iconUrl" :label="t('contributor.mcp.field.icon')" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.name') }}</label>
              <input v-model="name" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.serverName') }}</label>
              <input v-model="serverName" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
            <div v-if="props.mode === 'create'" class="grid grid-cols-2 gap-3">
              <div>
                <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.url') }}</label>
                <input v-model="url" type="text" :placeholder="t('contributor.mcp.placeholder.url')" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
              </div>
              <div>
                <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.transport') }}</label>
                <select v-model="transport" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none">
                  <option value="sse">{{ t('contributor.mcp.transport.sse') }}</option>
                  <option value="streamable_http">{{ t('contributor.mcp.transport.streamable') }}</option>
                </select>
              </div>
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.description') }}</label>
              <textarea v-model="description" rows="2" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.instructions') }}</label>
              <textarea v-model="instructions" rows="2" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.category') }}</label>
                <input v-model="category" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
              </div>
              <div>
                <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.author') }}</label>
                <input v-model="author" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
              </div>
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.tags') }}</label>
              <input v-model="tagsText" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.documentationUrl') }}</label>
                <input v-model="documentationUrl" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
              </div>
              <div>
                <label class="mb-1 block text-sm font-medium text-slate-700">{{ t('contributor.mcp.field.sourceUrl') }}</label>
                <input v-model="sourceUrl" type="text" class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none" />
              </div>
            </div>
          </template>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button class="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100" @click="emit('close')">{{ t('contributor.mcp.btn.cancel') }}</button>
          <button :disabled="saving" class="rounded-lg bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-700 disabled:opacity-50" @click="handleSubmit">{{ t('contributor.mcp.btn.save') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
