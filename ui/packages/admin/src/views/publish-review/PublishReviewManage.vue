<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  getPublishReviews,
  approvePublishReview,
  rejectPublishReview,
  getPublishSettings,
  updatePublishSettings,
  toast,
  type PublishReview,
  type PublishReviewStatus,
  type PublishReviewEntityType,
} from '@aihelms/shared'
import Pagination from '../../components/Pagination.vue'

const reviews = ref<PublishReview[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const submitting = ref(false)
const filterStatus = ref<string>('pending')
const filterType = ref<string>('')

const gateEnabled = ref(false)
const gateLoading = ref(false)

const reviewing = ref<PublishReview | null>(null)
const reviewAction = ref<'approve' | 'reject'>('approve')
const reviewNotes = ref('')

const ENTITY_LABELS: Record<PublishReviewEntityType, string> = {
  mcp_server: 'MCP',
  skill: 'Skill',
  custom_entity: '自定义实体',
}

async function loadReviews(): Promise<void> {
  loading.value = true
  try {
    const res = await getPublishReviews(page.value, pageSize.value, {
      status: (filterStatus.value || undefined) as PublishReviewStatus | undefined,
      entity_type: (filterType.value || undefined) as PublishReviewEntityType | undefined,
    })
    reviews.value = res.items
    total.value = res.total
  } catch (e) {
    toast.error((e as { message?: string }).message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadSettings(): Promise<void> {
  try {
    const res = await getPublishSettings()
    gateEnabled.value = res.publish_review_enabled
  } catch (e) {
    toast.error((e as { message?: string }).message || '门控设置加载失败')
  }
}

async function toggleGate(): Promise<void> {
  if (gateLoading.value) return
  gateLoading.value = true
  const next = !gateEnabled.value
  try {
    const res = await updatePublishSettings({ enabled: next })
    gateEnabled.value = res.publish_review_enabled
    toast.success(next ? '发布门控已开启' : '发布门控已关闭')
  } catch (e) {
    toast.error((e as { message?: string }).message || '门控设置更新失败')
  } finally {
    gateLoading.value = false
  }
}

function openReview(item: PublishReview, action: 'approve' | 'reject'): void {
  reviewing.value = item
  reviewAction.value = action
  reviewNotes.value = ''
}

function closeReviewDialog(): void {
  reviewing.value = null
  reviewNotes.value = ''
}

async function submitReview(): Promise<void> {
  if (!reviewing.value || submitting.value) return
  submitting.value = true
  try {
    if (reviewAction.value === 'approve') {
      await approvePublishReview(reviewing.value.id, { review_notes: reviewNotes.value })
      toast.success('发布申请已通过，资源已发布')
    } else {
      await rejectPublishReview(reviewing.value.id, { review_notes: reviewNotes.value })
      toast.success('发布申请已驳回')
    }
    closeReviewDialog()
    await loadReviews()
  } catch (e) {
    toast.error((e as { message?: string }).message || '审核失败')
  } finally {
    submitting.value = false
  }
}

function handleFilterChange(): void {
  page.value = 1
  loadReviews()
}

function handlePageChange(newPage: number): void {
  page.value = newPage
  loadReviews()
}

function statusColor(status: PublishReviewStatus): string {
  if (status === 'pending') return 'bg-amber-50 text-amber-700'
  if (status === 'approved') return 'bg-green-50 text-green-700'
  if (status === 'rejected') return 'bg-red-50 text-red-700'
  return 'bg-slate-100 text-slate-700'
}

function statusLabel(status: PublishReviewStatus): string {
  if (status === 'pending') return '待审核'
  if (status === 'approved') return '已通过'
  if (status === 'rejected') return '已驳回'
  return '已撤回'
}

function entityLabel(type: PublishReviewEntityType): string {
  return ENTITY_LABELS[type] || type
}

onMounted(() => {
  loadSettings()
  loadReviews()
})
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-slate-900">发布审核</h1>
      <p class="mt-1 text-sm text-slate-500">
        审核创建者的资源发布申请，通过后资源正式发布上架
      </p>
    </div>

    <div class="mb-4 flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4">
      <div>
        <div class="text-sm font-medium text-slate-900">发布门控</div>
        <div class="mt-0.5 text-xs text-slate-500">
          开启后，创建者发布 MCP / Skill / 自定义实体需管理员审核通过才生效；关闭则直接发布
        </div>
      </div>
      <button
        type="button"
        role="switch"
        :aria-checked="gateEnabled"
        :disabled="gateLoading"
        class="relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-60"
        :class="gateEnabled ? 'bg-purple-600' : 'bg-slate-300'"
        @click="toggleGate"
      >
        <span
          class="absolute left-0 top-1 inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
          :class="gateEnabled ? 'translate-x-6' : 'translate-x-1'"
        />
      </button>
    </div>

    <div class="mb-4 flex flex-wrap items-center gap-3">
      <select
        v-model="filterType"
        class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm focus:border-purple-500 focus:outline-none"
        @change="handleFilterChange"
      >
        <option value="">全部类型</option>
        <option value="mcp_server">MCP</option>
        <option value="skill">Skill</option>
        <option value="custom_entity">自定义实体</option>
      </select>
      <select
        v-model="filterStatus"
        class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm focus:border-purple-500 focus:outline-none"
        @change="handleFilterChange"
      >
        <option value="">全部状态</option>
        <option value="pending">待审核</option>
        <option value="approved">已通过</option>
        <option value="rejected">已驳回</option>
        <option value="withdrawn">已撤回</option>
      </select>
    </div>

    <div v-if="loading" class="py-12 text-center text-sm text-slate-500">加载中...</div>
    <div v-else-if="reviews.length === 0" class="py-12 text-center text-sm text-slate-500">
      暂无发布申请
    </div>
    <div v-else class="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table class="w-full text-sm">
        <thead class="bg-slate-50">
          <tr>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">资源类型</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">资源 ID</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">提交人</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">状态</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">备注</th>
            <th class="px-4 py-2.5 text-left font-medium text-slate-700">提交时间</th>
            <th class="px-4 py-2.5 text-right font-medium text-slate-700">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in reviews" :key="item.id" class="border-t border-slate-100">
            <td class="px-4 py-2.5 text-slate-700">
              <span class="rounded bg-purple-50 px-2 py-0.5 text-xs text-purple-700">
                {{ entityLabel(item.entity_type) }}
              </span>
            </td>
            <td class="px-4 py-2.5 text-slate-700">#{{ item.entity_id }}</td>
            <td class="px-4 py-2.5 text-slate-700">#{{ item.requested_by }}</td>
            <td class="px-4 py-2.5">
              <span class="rounded px-2 py-0.5 text-xs" :class="statusColor(item.status)">
                {{ statusLabel(item.status) }}
              </span>
            </td>
            <td class="px-4 py-2.5 max-w-xs truncate text-xs text-slate-600">
              {{ item.review_notes || '-' }}
            </td>
            <td class="px-4 py-2.5 text-xs text-slate-500">
              {{ item.created_at?.replace('T', ' ').slice(0, 19) }}
            </td>
            <td class="px-4 py-2.5 text-right">
              <div v-if="item.status === 'pending'" class="flex justify-end gap-2">
                <button
                  class="rounded-lg bg-green-50 px-3 py-1 text-xs font-medium text-green-700 hover:bg-green-100"
                  @click="openReview(item, 'approve')"
                >
                  通过
                </button>
                <button
                  class="rounded-lg bg-red-50 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
                  @click="openReview(item, 'reject')"
                >
                  驳回
                </button>
              </div>
              <span v-else class="text-xs text-slate-400">已处理</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Pagination
      v-if="total > 0"
      :page="page"
      :page-size="pageSize"
      :total="total"
      @change="handlePageChange"
    />

    <div v-if="reviewing" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div class="w-full max-w-md rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl">
        <h3 class="mb-4 text-lg font-semibold text-slate-900">
          {{ reviewAction === 'approve' ? '通过发布申请' : '驳回发布申请' }}
        </h3>
        <div class="mb-4 rounded-lg bg-slate-50 p-3 text-sm">
          <div class="mb-1 text-slate-700">
            资源：{{ entityLabel(reviewing.entity_type) }} #{{ reviewing.entity_id }}
          </div>
          <div class="text-xs text-slate-600">提交人：#{{ reviewing.requested_by }}</div>
        </div>
        <div class="mb-4">
          <label class="mb-1 block text-sm font-medium text-slate-700">审核备注</label>
          <textarea
            v-model="reviewNotes"
            rows="3"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
          />
        </div>
        <p v-if="reviewAction === 'approve'" class="mb-4 text-xs text-slate-500">
          通过后该资源将正式发布上架
        </p>
        <p v-else class="mb-4 text-xs text-slate-500">
          驳回后资源保持未发布，创建者可修改后重新提交
        </p>
        <div class="flex justify-end gap-3">
          <button
            class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
            :disabled="submitting"
            @click="closeReviewDialog"
          >
            取消
          </button>
          <button
            class="rounded-lg px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
            :class="
              reviewAction === 'approve'
                ? 'bg-green-600 hover:bg-green-700'
                : 'bg-red-600 hover:bg-red-700'
            "
            :disabled="submitting"
            @click="submitReview"
          >
            确认
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
