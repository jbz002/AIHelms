<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft } from 'lucide-vue-next'
import DocsInterfacePanel from '../../components/docs-center/DocsInterfacePanel.vue'
import { useDocsOwner } from '../../composables/useDocsOwner'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const libraryName = computed(() => route.params.libraryName as string)
const { canManage } = useDocsOwner(libraryName)

function back(): void {
  router.push({ name: 'DocsDocumentList', params: { libraryName: libraryName.value } })
}
</script>

<template>
  <div class="mx-auto max-w-7xl px-6 py-8">
    <div class="mb-4">
      <button class="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700" @click="back">
        <ArrowLeft class="h-4 w-4" />
        {{ t('docs.action.back') }}
      </button>
    </div>
    <DocsInterfacePanel :library-name="libraryName" :can-manage="canManage" />
  </div>
</template>
