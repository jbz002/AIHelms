<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getDocument } from '@aihelms/shared'
import { ArrowLeft } from 'lucide-vue-next'
import DocsInterfacePanel from '../../components/docs-center/DocsInterfacePanel.vue'
import { useDocsOwner } from '../../composables/useDocsOwner'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const libraryName = computed(() => route.params.libraryName as string)
const docId = computed(() => Number(route.params.docId))
const { canManage } = useDocsOwner(libraryName)
const docTitle = ref<string>('')

onMounted(async () => {
  try {
    const d = await getDocument(docId.value)
    docTitle.value = d.title || `#${docId.value}`
  } catch {
    docTitle.value = `#${docId.value}`
  }
})

function back(): void {
  // 两个入口（列表行操作 / 详情页按钮）共用此页：有历史则按来源返回，否则回退文档列表
  if (window.history.state?.back) {
    router.back()
  } else {
    router.push({ name: 'DocsDocumentList', params: { libraryName: libraryName.value } })
  }
}
</script>

<template>
  <div class="mx-auto max-w-7xl px-6 py-8">
    <div class="mb-4 flex items-center gap-3">
      <button class="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700" @click="back">
        <ArrowLeft class="h-4 w-4" />
        {{ t('docs.action.back') }}
      </button>
      <h1 class="text-base font-semibold text-slate-900">{{ t('docs.interfaces.docScope', { name: docTitle }) }}</h1>
    </div>
    <DocsInterfacePanel :library-name="libraryName" :doc-id="docId" :can-manage="canManage" />
  </div>
</template>
