<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  getSkillMarketDetail,
  getMcpServerMarketDetail,
  createResourceApplication,
  toast,
  type Skill,
  type McpServer,
} from '@aihelms/shared'

type DetailItem = (Skill & { _kind: 'skill' }) | (McpServer & { _kind: 'mcp' })

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const item = ref<DetailItem | null>(null)
const loading = ref(true)
const forbidden = ref(false)
const failed = ref(false)
const applyReason = ref('')
const applying = ref(false)

const resourceType = computed<'skill' | 'mcp'>(() =>
  route.params.type === 'skill' ? 'skill' : 'mcp',
)
const resourceId = computed(() => Number(route.params.id))
const isUnlisted = computed(() => item.value?.visibility_type === 'unlisted')
const needsApproval = computed(() => item.value?.requires_approval === true)

async function loadDetail(): Promise<void> {
  loading.value = true
  forbidden.value = false
  failed.value = false
  try {
    const data =
      resourceType.value === 'skill'
        ? await getSkillMarketDetail(resourceId.value)
        : await getMcpServerMarketDetail(resourceId.value)
    item.value = { ...data, _kind: resourceType.value } as DetailItem
  } catch (e) {
    const msg = (e as Error).message || ''
    forbidden.value = msg.includes('无权')
    failed.value = !forbidden.value
  } finally {
    loading.value = false
  }
}

async function handleApply(): Promise<void> {
  if (applying.value) return
  applying.value = true
  try {
    await createResourceApplication({
      resource_type: resourceType.value,
      resource_id: resourceId.value,
      reason: applyReason.value.trim(),
    })
    toast.success(t('market.detail.applySuccess'))
    applyReason.value = ''
  } catch {
    /* request 已提示 */
  } finally {
    applying.value = false
  }
}

function goMarket(): void {
  router.push({ name: 'Market' })
}

onMounted(loadDetail)
</script>

<template>
  <div class="mx-auto max-w-3xl px-6 py-8 space-y-6">
    <button class="text-sm text-slate-500 hover:text-slate-700" @click="goMarket">
      ← {{ t('market.detail.back') }}
    </button>

    <div v-if="loading" class="flex items-center justify-center py-20">
      <div class="h-8 w-8 animate-spin rounded-full border-2 border-purple-500 border-t-transparent" />
    </div>

    <div v-else-if="forbidden" class="py-20 text-center text-slate-500">
      {{ t('market.detail.noPermission') }}
    </div>

    <div v-else-if="failed" class="py-20 text-center text-slate-500">
      {{ t('market.detail.notFound') }}
    </div>

    <template v-else-if="item">
      <div v-if="isUnlisted" class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
        {{ t('market.detail.unlistedTip') }}
      </div>

      <div class="rounded-2xl border border-slate-200/60 bg-white p-6">
        <div class="mb-2 flex items-center gap-3">
          <span
            class="rounded-md px-2 py-0.5 text-xs font-medium"
            :class="item._kind === 'skill' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'"
          >
            {{ item._kind === 'skill' ? t('market.detail.typeSkill') : t('market.detail.typeMcp') }}
          </span>
          <h1 class="text-xl font-bold text-slate-800">{{ item.name }}</h1>
        </div>
        <p v-if="item.author" class="mb-3 text-xs text-slate-400">{{ item.author }}</p>
        <p v-if="item.description" class="whitespace-pre-wrap text-sm leading-relaxed text-slate-600">{{ item.description }}</p>
        <div v-if="item.tags?.length" class="mt-3 flex flex-wrap gap-1">
          <span
            v-for="tag in item.tags"
            :key="tag"
            class="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500"
          >{{ tag }}</span>
        </div>
      </div>

      <div class="space-y-3 rounded-2xl border border-slate-200/60 bg-white p-6">
        <template v-if="needsApproval">
          <label class="block text-sm font-medium text-slate-700">{{ t('market.detail.applyReason') }}</label>
          <textarea
            v-model="applyReason"
            rows="3"
            :placeholder="t('market.detail.applyPlaceholder')"
            class="w-full rounded-xl border border-slate-200/60 bg-white px-4 py-3 text-sm focus:border-purple-300 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
          />
          <button
            :disabled="!applyReason.trim() || applying"
            class="rounded-lg bg-gradient-to-r from-purple-500 to-blue-500 px-4 py-2 text-sm font-medium text-white shadow-sm disabled:opacity-50"
            @click="handleApply"
          >
            {{ applying ? t('market.detail.applying') : t('market.detail.apply') }}
          </button>
        </template>
        <div v-else class="flex items-center justify-between">
          <p class="text-sm text-slate-500">{{ t('market.detail.noApproval') }}</p>
          <button
            class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
            @click="goMarket"
          >
            {{ t('market.detail.goMarket') }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
