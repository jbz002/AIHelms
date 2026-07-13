<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getDocsMcpLibraryDetail,
  searchDocsMcp,
  deleteDocsMcpVersion,
  refreshDocsMcpVersion,
  toast,
  type DocsMcpLibrary,
  type DocsMcpSearchResult,
} from '@aihelms/shared'
import { ArrowLeft, ExternalLink, Plus, Loader2 } from 'lucide-vue-next'
import SearchCard from './components/SearchCard.vue'
import SearchResultList from './components/SearchResultList.vue'
import VersionRow from './components/VersionRow.vue'
import ScrapeJobDialog from './components/ScrapeJobDialog.vue'

const route = useRoute()
const router = useRouter()
const libraryName = route.params.libraryName as string

const library = ref<DocsMcpLibrary | null>(null)
const searchResults = ref<DocsMcpSearchResult[]>([])
const searchLoading = ref(false)
const hasSearched = ref(false)
const loading = ref(false)
const showAddVersionDialog = ref(false)

async function loadLibrary(): Promise<void> {
  loading.value = true
  try {
    library.value = await getDocsMcpLibraryDetail(libraryName)
  } catch (e) {
    toast.error((e as Error).message || '加载文档库失败')
  } finally {
    loading.value = false
  }
}

async function handleSearch(query: string, version: string | null): Promise<void> {
  searchLoading.value = true
  hasSearched.value = true
  try {
    searchResults.value = await searchDocsMcp(
      libraryName,
      query,
      version || undefined,
      20,
    )
  } catch (e) {
    toast.error((e as Error).message || '搜索失败')
  } finally {
    searchLoading.value = false
  }
}

async function handleDeleteVersion(version: string): Promise<void> {
  try {
    await deleteDocsMcpVersion(libraryName, version)
    toast.success('版本已删除')
    await loadLibrary()
  } catch (e) {
    toast.error((e as Error).message || '删除失败')
  }
}

async function handleRefreshVersion(
  _library: string,
  version: string,
  versionId: number,
): Promise<void> {
  try {
    await refreshDocsMcpVersion(String(versionId), {
      library: libraryName,
      version: version || null,
    })
    toast.success('刷新任务已创建')
  } catch (e) {
    toast.error((e as Error).message || '刷新失败')
  }
}

function goBack(): void {
  router.push({ name: 'DocsMcp' })
}

onMounted(() => {
  loadLibrary()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center gap-3">
      <button
        class="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        @click="goBack"
      >
        <ArrowLeft class="h-5 w-5" />
      </button>
      <div v-if="library" class="min-w-0 flex-1">
        <h1 class="truncate text-xl font-bold text-gray-900">{{ libraryName }}</h1>
        <a
          v-if="library.versions.length > 0 && library.versions[0].sourceUrl"
          :href="library.versions[0].sourceUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700"
        >
          {{ library.versions[0].sourceUrl }}
          <ExternalLink class="h-3 w-3" />
        </a>
      </div>
      <button
        class="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        @click="showAddVersionDialog = true"
      >
        <Plus class="h-4 w-4" />
        新增版本
      </button>
    </div>

    <Loader2 v-if="loading" class="mx-auto h-8 w-8 animate-spin text-gray-300" />

    <template v-if="library">
      <SearchCard :versions="library.versions" @search="handleSearch" />
      <SearchResultList :results="searchResults" :loading="searchLoading" />

      <div>
        <h3 class="mb-3 text-sm font-semibold text-gray-700">
          版本列表
          <span class="font-normal text-gray-400">({{ library.versions.length }})</span>
        </h3>
        <div v-if="library.versions.length === 0" class="rounded-lg border border-dashed border-gray-200 py-6 text-center">
          <p class="text-sm text-gray-400">暂无版本</p>
        </div>
        <div v-else class="space-y-2">
          <VersionRow
            v-for="ver in library.versions"
            :key="ver.ref.version || '_default'"
            :version="ver"
            :library-name="libraryName"
            @refresh="handleRefreshVersion"
            @delete="handleDeleteVersion"
          />
        </div>
      </div>
    </template>

    <ScrapeJobDialog
      :visible="showAddVersionDialog"
      :default-library="libraryName"
      @close="showAddVersionDialog = false"
      @submit="() => { showAddVersionDialog = false; loadLibrary() }"
    />
  </div>
</template>
