<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePermission, listLibraries, createLibrary, toast } from '@aihelms/shared'
import type { DocumentLibrary } from '@aihelms/shared'
import { Library, Plus, Loader2, Search, X } from 'lucide-vue-next'
import DocsInterfacePanel from '../components/docs-center/DocsInterfacePanel.vue'
import DocsDocumentPanel from '../components/docs-center/DocsDocumentPanel.vue'

const { t } = useI18n()
const { hasPermission } = usePermission()

const loading = ref(false)
const libraries = ref<DocumentLibrary[]>([])
const selectedName = ref<string | null>(null)
const keyword = ref('')
const activeTab = ref<'interfaces' | 'documents'>('interfaces')

const filteredLibraries = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return libraries.value
  return libraries.value.filter((l) => l.name.toLowerCase().includes(kw) || (l.description ?? '').toLowerCase().includes(kw))
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const res = await listLibraries(1, 100)
    libraries.value = res.items
    if (libraries.value.length && !selectedName.value) {
      selectedName.value = libraries.value[0].name
    }
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

// 新建库
const createVisible = ref(false)
const formName = ref('')
const formDesc = ref('')
const creating = ref(false)

function openCreate(): void {
  formName.value = ''
  formDesc.value = ''
  createVisible.value = true
}

async function confirmCreate(): Promise<void> {
  if (!formName.value.trim()) return
  creating.value = true
  try {
    const lib = await createLibrary(formName.value.trim(), formDesc.value)
    toast.success(t('docs.library.createSuccess'))
    createVisible.value = false
    libraries.value = [lib, ...libraries.value]
    selectedName.value = lib.name
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    creating.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-7xl px-6 py-8">
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-slate-900">{{ t('docs.title') }}</h1>
      <p class="mt-1 text-sm text-slate-500">{{ t('docs.subtitle') }}</p>
    </div>

    <div v-if="!hasPermission('document:read')" class="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-700">
      {{ t('docs.msg.noPermission') }}
    </div>

    <div v-else class="flex flex-col gap-4 lg:flex-row">
      <!-- 库侧栏 -->
      <aside class="w-full shrink-0 lg:w-64">
        <div class="rounded-lg border border-slate-200 bg-white shadow-sm">
          <div class="border-b border-slate-100 p-3">
            <div class="relative">
              <Search class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                v-model="keyword"
                :placeholder="t('docs.library.searchPlaceholder')"
                class="w-full rounded-md border border-slate-200 py-1.5 pl-8 pr-2 text-sm focus:border-purple-400 focus:outline-none"
              />
            </div>
            <button
              class="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700"
              @click="openCreate"
            >
              <Plus class="h-4 w-4" />
              {{ t('docs.library.create') }}
            </button>
          </div>

          <div v-if="loading" class="flex h-40 items-center justify-center">
            <Loader2 class="h-5 w-5 animate-spin text-slate-400" />
          </div>
          <div v-else-if="!filteredLibraries.length" class="p-6 text-center text-xs text-slate-400">
            {{ t('docs.library.empty') }}
          </div>
          <ul v-else class="max-h-[70vh] divide-y divide-slate-50 overflow-y-auto">
            <li v-for="lib in filteredLibraries" :key="lib.id">
              <button
                class="flex w-full flex-col items-start px-3 py-2.5 text-left transition-colors"
                :class="selectedName === lib.name ? 'bg-purple-50' : 'hover:bg-slate-50'"
                @click="selectedName = lib.name"
              >
                <span class="flex items-center gap-1.5 text-sm font-medium" :class="selectedName === lib.name ? 'text-purple-700' : 'text-slate-700'">
                  <Library class="h-3.5 w-3.5 shrink-0" />
                  <span class="truncate">{{ lib.name }}</span>
                </span>
                <span class="mt-0.5 pl-5 text-xs text-slate-400">
                  {{ lib.document_count }} {{ t('docs.library.docs') }} · {{ lib.total_chunks }} {{ t('docs.library.chunks') }}
                </span>
              </button>
            </li>
          </ul>
        </div>
      </aside>

      <!-- 主区 -->
      <main class="min-w-0 flex-1">
        <template v-if="selectedName">
          <div class="mb-3 flex gap-1 border-b border-slate-200">
            <button
              class="-mb-px border-b-2 px-4 py-2 text-sm transition-colors"
              :class="activeTab === 'interfaces' ? 'border-purple-600 font-medium text-purple-700' : 'border-transparent text-slate-500 hover:text-slate-700'"
              @click="activeTab = 'interfaces'"
            >{{ t('docs.tab.interfaces') }}</button>
            <button
              class="-mb-px border-b-2 px-4 py-2 text-sm transition-colors"
              :class="activeTab === 'documents' ? 'border-purple-600 font-medium text-purple-700' : 'border-transparent text-slate-500 hover:text-slate-700'"
              @click="activeTab = 'documents'"
            >{{ t('docs.tab.documents') }}</button>
          </div>

          <DocsInterfacePanel v-if="activeTab === 'interfaces'" :library-name="selectedName" />
          <DocsDocumentPanel v-else :library-name="selectedName" />
        </template>
        <div v-else-if="!loading" class="flex h-60 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white text-sm text-slate-400">
          {{ t('docs.library.empty') }}
        </div>
      </main>
    </div>

    <!-- 新建库 modal -->
    <Teleport to="body">
      <div v-if="createVisible" class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 p-4" @click.self="createVisible = false">
        <div class="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
          <div class="mb-4 flex items-center justify-between">
            <h3 class="text-base font-semibold text-slate-900">{{ t('docs.library.create') }}</h3>
            <button class="text-slate-400 hover:text-slate-600" @click="createVisible = false">
              <X class="h-5 w-5" />
            </button>
          </div>
          <div class="space-y-3">
            <div>
              <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.library.name') }}</label>
              <input
                v-model="formName"
                :placeholder="t('docs.library.namePlaceholder')"
                class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 text-sm focus:border-purple-400 focus:outline-none"
              />
            </div>
            <div>
              <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.library.description') }}</label>
              <textarea
                v-model="formDesc"
                rows="2"
                :placeholder="t('docs.library.descriptionPlaceholder')"
                class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 text-sm focus:border-purple-400 focus:outline-none"
              />
            </div>
          </div>
          <div class="mt-5 flex justify-end gap-2">
            <button class="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100" @click="createVisible = false">{{ t('docs.library.cancel') }}</button>
            <button
              class="flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
              :disabled="creating || !formName.trim()"
              @click="confirmCreate"
            >
              <Loader2 v-if="creating" class="h-4 w-4 animate-spin" />
              {{ t('docs.library.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
