<script setup lang="ts">
import { ref, watch } from 'vue'
import type { DocsMcpScrapeOptions } from '@aihelms/shared'
import { X } from 'lucide-vue-next'
import AddVersionCrawlForm from './AddVersionCrawlForm.vue'
import AddVersionUploadForm from './AddVersionUploadForm.vue'

type CrawlIngestMode = 'direct' | 'crawl-only'

interface CrawlSubmitParams {
  url: string
  library: string
  version: string
  options: DocsMcpScrapeOptions
  ingestMode: CrawlIngestMode
}

interface Props {
  visible: boolean
  defaultLibrary: string
  defaultVersion?: string
}

interface Emits {
  close: []
  'crawl-submit': [params: CrawlSubmitParams]
  uploaded: []
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const activeTab = ref<'crawl' | 'upload'>('crawl')

// 每次打开默认回到爬虫 tab
watch(
  () => props.visible,
  (v) => {
    if (v) activeTab.value = 'crawl'
  },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div class="relative w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <button class="absolute right-4 top-4 rounded-md p-1 text-gray-400 hover:bg-gray-100" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
        <h3 class="mb-4 text-lg font-semibold text-gray-900">新增版本</h3>

        <div class="mb-4 flex gap-1 border-b border-gray-200">
          <button
            class="-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors"
            :class="activeTab === 'crawl' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'"
            @click="activeTab = 'crawl'"
          >
            爬虫入库
          </button>
          <button
            class="-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors"
            :class="activeTab === 'upload' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'"
            @click="activeTab = 'upload'"
          >
            上传文件
          </button>
        </div>

        <AddVersionCrawlForm
          v-if="activeTab === 'crawl'"
          :default-library="defaultLibrary"
          :default-version="defaultVersion"
          @close="emit('close')"
          @submit="(params) => emit('crawl-submit', params)"
        />
        <AddVersionUploadForm
          v-if="activeTab === 'upload'"
          :default-library="defaultLibrary"
          :default-version="defaultVersion"
          @close="emit('close')"
          @uploaded="emit('uploaded')"
        />
      </div>
    </div>
  </Teleport>
</template>
