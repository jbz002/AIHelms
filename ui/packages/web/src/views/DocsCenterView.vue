<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePermission, useAuth, listLibraries, createLibrary, updateLibrary, deleteLibrary, uploadDocumentsBatch, toast } from '@aihelms/shared'
import type { DocumentLibrary } from '@aihelms/shared'
import { Library, Plus, Pencil, Trash2, Loader2, Search, X, FileText, Upload } from 'lucide-vue-next'
import DocsInterfacePanel from '../components/docs-center/DocsInterfacePanel.vue'
import DocsDocumentPanel from '../components/docs-center/DocsDocumentPanel.vue'

const { t } = useI18n()
const { hasPermission } = usePermission()
const { currentUser } = useAuth()

function isLibraryOwner(lib: DocumentLibrary): boolean {
  const u = currentUser.value
  return !!u && (u.is_admin || lib.created_by === u.id)
}

const loading = ref(false)
const libraries = ref<DocumentLibrary[]>([])
const selectedName = ref<string | null>(null)
const keyword = ref('')
const scope = ref<'all' | 'mine'>('mine')
const activeTab = ref<'interfaces' | 'documents'>('documents')

const selectedLib = computed(
  () => libraries.value.find((l) => l.name === selectedName.value) ?? null,
)
const canManage = computed(() => (selectedLib.value ? isLibraryOwner(selectedLib.value) : false))

const filteredLibraries = computed(() => {
  let list = libraries.value
  if (scope.value === 'mine') list = list.filter(isLibraryOwner)
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return list
  return list.filter((l) => l.name.toLowerCase().includes(kw) || (l.description ?? '').toLowerCase().includes(kw))
})

// 切 scope/搜索后，当前选中库若不在过滤结果内，默认选第一个（无则清空）
watch(filteredLibraries, (list) => {
  if (!list.some((l) => l.name === selectedName.value)) {
    selectedName.value = list[0]?.name ?? null
  }
})

// 主区空状态文案：我的范围无库 → 引导新建；否则通用空提示
const mainEmptyText = computed(() =>
  scope.value === 'mine' ? t('docs.library.mineEmpty') : t('docs.library.empty'),
)

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

// 新建/编辑库 modal
const modalOpen = ref(false)
const modalMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | null>(null)
const formName = ref('')
const formDesc = ref('')
const formVersion = ref('1.0.0')
const formFiles = ref<File[]>([])
const creating = ref(false)
const DOCS_VERSION_RE = /^v?\d+\.\d+\.\d+$/

function openCreate(): void {
  modalMode.value = 'create'
  editingId.value = null
  formName.value = ''
  formDesc.value = ''
  formVersion.value = '1.0.0'
  formFiles.value = []
  modalOpen.value = true
}

function onModalFileChange(e: Event): void {
  const target = e.target as HTMLInputElement
  const picked = target.files ? Array.from(target.files) : []
  if (picked.length) formFiles.value = [...formFiles.value, ...picked]
  target.value = ''
}

function removeFormFile(index: number): void {
  formFiles.value = formFiles.value.filter((_, i) => i !== index)
}

function openEdit(lib: DocumentLibrary): void {
  modalMode.value = 'edit'
  editingId.value = lib.id
  formName.value = lib.name
  formDesc.value = lib.description ?? ''
  modalOpen.value = true
}

async function confirmModal(): Promise<void> {
  if (!formName.value.trim()) return
  const ver = formVersion.value.trim()
  if (modalMode.value === 'create') {
    if (!DOCS_VERSION_RE.test(ver)) {
      toast.error(t('docs.addVersion.versionInvalid'))
      return
    }
    if (formFiles.value.length === 0) {
      toast.error(t('docs.addVersion.noFile'))
      return
    }
  }
  creating.value = true
  try {
    if (modalMode.value === 'create') {
      const lib = await createLibrary(formName.value.trim(), formDesc.value)
      try {
        await uploadDocumentsBatch(lib.name, formFiles.value, ver, true)
      } catch (uploadErr) {
        // 库已建，上传失败：选中库让用户在文档面板重试上传
        toast.error((uploadErr as Error).message)
        await load()
        selectedName.value = lib.name
        modalOpen.value = false
        return
      }
      toast.success(t('docs.library.createSuccess'))
      await load()
      selectedName.value = lib.name
      modalOpen.value = false
    } else if (editingId.value !== null) {
      const lib = await updateLibrary(editingId.value, {
        name: formName.value.trim(),
        description: formDesc.value,
      })
      toast.success(t('docs.library.editSuccess'))
      const idx = libraries.value.findIndex((l) => l.id === editingId.value)
      if (idx !== -1) libraries.value[idx] = lib
      if (selectedName.value !== lib.name) selectedName.value = lib.name
    }
    modalOpen.value = false
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    creating.value = false
  }
}

async function handleDeleteLib(lib: DocumentLibrary): Promise<void> {
  if (!window.confirm(t('docs.library.confirmDelete', { name: lib.name }))) return
  try {
    await deleteLibrary(lib.id)
    toast.success(t('docs.library.deleteSuccess'))
    libraries.value = libraries.value.filter((l) => l.id !== lib.id)
    if (selectedName.value === lib.name) {
      selectedName.value = libraries.value[0]?.name ?? null
    }
  } catch (e) {
    toast.error((e as Error).message)
  }
}

function onLibDeleted(): void {
  selectedName.value = null
  load()
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
            <div class="mb-2 flex rounded-md bg-slate-100 p-0.5 text-xs">
              <button
                class="flex-1 rounded py-1 font-medium transition-colors"
                :class="scope === 'all' ? 'bg-white text-purple-700 shadow-sm' : 'text-slate-500'"
                @click="scope = 'all'"
              >{{ t('docs.scope.all') }}</button>
              <button
                class="flex-1 rounded py-1 font-medium transition-colors"
                :class="scope === 'mine' ? 'bg-white text-purple-700 shadow-sm' : 'text-slate-500'"
                @click="scope = 'mine'"
              >{{ t('docs.scope.mine') }}</button>
            </div>
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
            <li
              v-for="lib in filteredLibraries"
              :key="lib.id"
              class="group flex items-start gap-1 px-2 py-2 transition-colors"
              :class="selectedName === lib.name ? 'bg-purple-50' : 'hover:bg-slate-50'"
            >
              <button class="flex min-w-0 flex-1 flex-col items-start text-left" @click="selectedName = lib.name">
                <span class="flex items-center gap-1.5 text-sm font-medium" :class="selectedName === lib.name ? 'text-purple-700' : 'text-slate-700'">
                  <Library class="h-3.5 w-3.5 shrink-0" />
                  <span class="truncate">{{ lib.name }}</span>
                </span>
                <span class="mt-0.5 pl-5 text-xs text-slate-400">
                  {{ lib.document_count }} {{ t('docs.library.docs') }} · {{ lib.total_chunks }} {{ t('docs.library.chunks') }}
                </span>
              </button>
              <div v-if="isLibraryOwner(lib)" class="flex shrink-0 items-center gap-0.5 pt-0.5">
                <button
                  class="rounded p-1 text-slate-400 hover:bg-white hover:text-purple-600"
                  :title="t('docs.library.edit')"
                  @click.stop="openEdit(lib)"
                >
                  <Pencil class="h-3.5 w-3.5" />
                </button>
                <button
                  class="rounded p-1 text-slate-400 hover:bg-white hover:text-red-600"
                  :title="t('docs.library.delete')"
                  @click.stop="handleDeleteLib(lib)"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                </button>
              </div>
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
              :class="activeTab === 'documents' ? 'border-purple-600 font-medium text-purple-700' : 'border-transparent text-slate-500 hover:text-slate-700'"
              @click="activeTab = 'documents'"
            >{{ t('docs.tab.documents') }}</button>
            <button
              class="-mb-px border-b-2 px-4 py-2 text-sm transition-colors"
              :class="activeTab === 'interfaces' ? 'border-purple-600 font-medium text-purple-700' : 'border-transparent text-slate-500 hover:text-slate-700'"
              @click="activeTab = 'interfaces'"
            >{{ t('docs.tab.interfaces') }}</button>
          </div>

          <DocsDocumentPanel v-if="activeTab === 'documents'" :library-name="selectedName" :library-id="selectedLib?.id ?? null" :can-manage="canManage" @library-deleted="onLibDeleted" />
          <DocsInterfacePanel v-else :library-name="selectedName" :can-manage="canManage" />
        </template>
        <div v-else-if="!loading" class="flex h-60 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-white text-sm text-slate-400">
          <FileText class="h-8 w-8 text-slate-300" />
          <span>{{ mainEmptyText }}</span>
        </div>
      </main>
    </div>

    <!-- 新建/编辑库 modal -->
    <Teleport to="body">
      <div v-if="modalOpen" class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 p-4" @click.self="modalOpen = false">
        <div class="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
          <div class="mb-4 flex items-center justify-between">
            <h3 class="text-base font-semibold text-slate-900">{{ modalMode === 'create' ? t('docs.library.create') : t('docs.library.editTitle') }}</h3>
            <button class="text-slate-400 hover:text-slate-600" @click="modalOpen = false">
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
            <template v-if="modalMode === 'create'">
              <div>
                <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.addVersion.version') }} *</label>
                <input
                  v-model="formVersion"
                  :placeholder="t('docs.addVersion.versionPlaceholder')"
                  class="w-full rounded-md border border-slate-200 px-2.5 py-1.5 text-sm focus:border-purple-400 focus:outline-none"
                />
              </div>
              <div>
                <label class="mb-1 block text-xs font-medium text-slate-500">{{ t('docs.addVersion.file') }} *</label>
                <label class="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-slate-300 p-3 transition-colors hover:border-purple-400 hover:bg-purple-50/50">
                  <Upload class="h-4 w-4 shrink-0 text-slate-400" />
                  <span class="text-xs text-slate-500">{{ t('docs.addVersion.pickFile') }}</span>
                  <input type="file" multiple class="hidden" @change="onModalFileChange" />
                </label>
                <div v-if="formFiles.length" class="mt-1.5 space-y-1">
                  <div
                    v-for="(f, i) in formFiles"
                    :key="`${f.name}-${f.size}-${i}`"
                    class="flex items-center gap-2 rounded border border-slate-200 px-2 py-1 text-xs"
                  >
                    <FileText class="h-3.5 w-3.5 shrink-0 text-purple-500" />
                    <span class="min-w-0 flex-1 truncate text-slate-700">{{ f.name }}</span>
                    <button class="shrink-0 text-slate-400 hover:text-red-500" type="button" @click="removeFormFile(i)">
                      <X class="h-3 w-3" />
                    </button>
                  </div>
                </div>
              </div>
            </template>
          </div>
          <div class="mt-5 flex justify-end gap-2">
            <button class="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100" @click="modalOpen = false">{{ t('docs.library.cancel') }}</button>
            <button
              class="flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
              :disabled="creating || !formName.trim() || (modalMode === 'create' && (!DOCS_VERSION_RE.test(formVersion.trim()) || formFiles.length === 0))"
              @click="confirmModal"
            >
              <Loader2 v-if="creating" class="h-4 w-4 animate-spin" />
              {{ modalMode === 'create' ? t('docs.library.confirm') : t('docs.library.save') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
