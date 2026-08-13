<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { usePermission, useAuth, listLibraries, createLibrary, updateLibrary, deleteLibrary, uploadDocumentsBatch, toast } from '@aihelms/shared'
import type { DocumentLibrary } from '@aihelms/shared'
import { Library, Plus, Pencil, Trash2, Loader2, Search, X, FileText, Upload } from 'lucide-vue-next'

const router = useRouter()
const { t } = useI18n()
const { hasPermission } = usePermission()
const { currentUser } = useAuth()

function isLibraryOwner(lib: DocumentLibrary): boolean {
  const u = currentUser.value
  return !!u && (u.is_admin || lib.created_by === u.id)
}

const loading = ref(false)
const libraries = ref<DocumentLibrary[]>([])
const keyword = ref('')
const scope = ref<'all' | 'mine'>('mine')

const filteredLibraries = computed(() => {
  let list = libraries.value
  if (scope.value === 'mine') list = list.filter(isLibraryOwner)
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return list
  return list.filter((l) => l.name.toLowerCase().includes(kw) || (l.description ?? '').toLowerCase().includes(kw))
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
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

function goLibrary(lib: DocumentLibrary): void {
  router.push({ name: 'DocsDocumentList', params: { libraryName: lib.name } })
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
        // 库已建，上传失败：刷新首页让用户进库重试上传
        toast.error((uploadErr as Error).message)
        await load()
        modalOpen.value = false
        return
      }
      toast.success(t('docs.library.createSuccess'))
      await load()
      modalOpen.value = false
    } else if (editingId.value !== null) {
      const lib = await updateLibrary(editingId.value, {
        name: formName.value.trim(),
        description: formDesc.value,
      })
      toast.success(t('docs.library.editSuccess'))
      const idx = libraries.value.findIndex((l) => l.id === editingId.value)
      if (idx !== -1) libraries.value[idx] = lib
      modalOpen.value = false
    }
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
  } catch (e) {
    toast.error((e as Error).message)
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-slate-900">{{ t('docs.title') }}</h1>
      <p class="mt-1 text-sm text-slate-500">{{ t('docs.subtitle') }}</p>
    </div>

    <div v-if="!hasPermission('document:read')" class="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-700">
      {{ t('docs.msg.noPermission') }}
    </div>

    <template v-else>
      <!-- 工具栏 -->
      <div class="mb-5 flex flex-wrap items-center gap-2">
        <div class="flex rounded-md bg-slate-100 p-0.5 text-xs">
          <button
            class="rounded px-3 py-1.5 font-medium transition-colors"
            :class="scope === 'all' ? 'bg-white text-purple-700 shadow-sm' : 'text-slate-500'"
            @click="scope = 'all'"
          >{{ t('docs.scope.all') }}</button>
          <button
            class="rounded px-3 py-1.5 font-medium transition-colors"
            :class="scope === 'mine' ? 'bg-white text-purple-700 shadow-sm' : 'text-slate-500'"
            @click="scope = 'mine'"
          >{{ t('docs.scope.mine') }}</button>
        </div>
        <div class="relative min-w-[14rem] flex-1">
          <Search class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            v-model="keyword"
            :placeholder="t('docs.library.searchPlaceholder')"
            class="w-full rounded-md border border-slate-200 py-1.5 pl-8 pr-2 text-sm focus:border-purple-400 focus:outline-none"
          />
        </div>
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700"
          @click="openCreate"
        >
          <Plus class="h-4 w-4" />
          {{ t('docs.library.create') }}
        </button>
      </div>

      <div v-if="loading" class="flex h-60 items-center justify-center">
        <Loader2 class="h-6 w-6 animate-spin text-slate-400" />
      </div>

      <div
        v-else-if="!filteredLibraries.length"
        class="flex h-60 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-white text-sm text-slate-400"
      >
        <FileText class="h-8 w-8 text-slate-300" />
        <span>{{ mainEmptyText }}</span>
      </div>

      <!-- 库卡片网格 -->
      <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="lib in filteredLibraries"
          :key="lib.id"
          class="group relative cursor-pointer rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition-colors hover:border-purple-300 hover:shadow"
          @click="goLibrary(lib)"
        >
          <div class="flex items-start gap-2">
            <Library class="h-5 w-5 shrink-0 text-purple-500" />
            <div class="min-w-0 flex-1">
              <h3 class="truncate text-sm font-semibold text-slate-900">{{ lib.name }}</h3>
              <p class="mt-1 line-clamp-2 text-xs text-slate-500">{{ lib.description || '—' }}</p>
            </div>
          </div>
          <div class="mt-3 flex items-center gap-3 text-xs text-slate-400">
            <span>{{ lib.document_count }} {{ t('docs.library.docs') }}</span>
            <span>{{ lib.total_chunks }} {{ t('docs.library.chunks') }}</span>
          </div>
          <div v-if="isLibraryOwner(lib)" class="absolute right-2 top-2 flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100" @click.stop>
            <button
              class="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-purple-600"
              :title="t('docs.library.edit')"
              @click="openEdit(lib)"
            >
              <Pencil class="h-3.5 w-3.5" />
            </button>
            <button
              class="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-red-600"
              :title="t('docs.library.delete')"
              @click="handleDeleteLib(lib)"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>
    </template>

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
