<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { StarRating, FeedbackList, getRating, rateResource, listFeedbacks, toast } from '@aihelms/shared'
import type { EntityType, FeedbackItem, FeedbackType, RatingView } from '@aihelms/shared'

interface Props {
  entityType: EntityType
  entityId: number
}

const props = defineProps<Props>()
const emit = defineEmits<{ rated: [{ avgScore: number; ratingCount: number }] }>()

const { t } = useI18n()

const view = ref<RatingView | null>(null)
const myScore = ref(0)
const myFeedbackType = ref<FeedbackType>('')
const comment = ref('')
const submitting = ref(false)

const feedbacks = ref<FeedbackItem[]>([])
const feedbackTotal = ref(0)
const feedbackPage = ref(1)
const feedbackPageSize = 5
const feedbackFilter = ref<FeedbackType>('')

const ratingLabels = computed(() => ({
  empty: t('market.rating.emptyFeedback'),
  anonymous: t('market.rating.anonymous'),
  prev: t('market.rating.prev'),
  next: t('market.rating.next'),
  types: {
    bug: t('market.rating.typeBug'),
    suggestion: t('market.rating.typeSuggestion'),
    praise: t('market.rating.typePraise'),
  } as Record<FeedbackType, string>,
}))

async function loadView() {
  try {
    view.value = await getRating(props.entityType, props.entityId)
    myScore.value = view.value.my_score ?? 0
    myFeedbackType.value = view.value.my_feedback_type ?? ''
    comment.value = view.value.my_comment ?? ''
  } catch { /* ignore */ }
}

async function loadFeedbacks(page: number) {
  feedbackPage.value = page
  try {
    const res = await listFeedbacks(
      props.entityType,
      props.entityId,
      page,
      feedbackPageSize,
      feedbackFilter.value || undefined,
    )
    feedbacks.value = res.items
    feedbackTotal.value = res.total
  } catch { /* ignore */ }
}

async function handleSubmit() {
  if (myScore.value < 1 || submitting.value) return
  submitting.value = true
  try {
    await rateResource(props.entityType, props.entityId, {
      score: myScore.value,
      feedback_type: myFeedbackType.value,
      comment: comment.value,
    })
    toast.success(t('market.rating.submitSuccess'))
    await loadView()
    await loadFeedbacks(1)
    if (view.value) {
      emit('rated', { avgScore: view.value.avg_score, ratingCount: view.value.rating_count })
    }
  } catch { /* toast handled by request layer */ }
  finally { submitting.value = false }
}

watch(() => feedbackFilter.value, () => loadFeedbacks(1))
watch(() => props.entityId, () => { loadView(); loadFeedbacks(1) })

onMounted(() => {
  loadView()
  loadFeedbacks(1)
})
</script>

<template>
  <div class="space-y-4">
    <!-- My rating -->
    <div>
      <div class="mb-2 flex items-center justify-between">
        <span class="text-xs font-semibold text-slate-700">{{ t('market.rating.myScore') }}</span>
        <span v-if="view && view.rating_count > 0" class="text-xs text-slate-400">
          {{ t('market.rating.basedOn', { count: view.rating_count }) }}
        </span>
        <span v-else class="text-xs text-slate-400">{{ t('market.rating.noRatings') }}</span>
      </div>
      <StarRating v-model="myScore" size="lg" />
      <div class="mt-3 flex flex-col gap-2">
        <select
          v-model="myFeedbackType"
          class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 focus:border-purple-300 focus:outline-none"
        >
          <option value="">{{ t('market.rating.feedbackType') }}</option>
          <option value="bug">{{ t('market.rating.typeBug') }}</option>
          <option value="suggestion">{{ t('market.rating.typeSuggestion') }}</option>
          <option value="praise">{{ t('market.rating.typePraise') }}</option>
        </select>
        <textarea
          v-model="comment"
          rows="2"
          :placeholder="t('market.rating.commentPlaceholder')"
          class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-purple-300 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
        />
        <button
          type="button"
          class="self-start rounded-lg bg-gradient-to-r from-purple-500 to-blue-500 px-4 py-1.5 text-xs font-medium text-white shadow-sm disabled:opacity-50"
          :disabled="myScore < 1 || submitting"
          @click="handleSubmit"
        >
          {{ submitting ? t('market.rating.submitting') : t('market.rating.submit') }}
        </button>
      </div>
    </div>

    <!-- Feedback list -->
    <div>
      <div class="mb-2 flex items-center justify-between">
        <span class="text-xs font-semibold text-slate-700">{{ t('market.rating.feedbackTitle') }}</span>
        <select
          v-model="feedbackFilter"
          class="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-600 focus:outline-none"
        >
          <option value="">{{ t('market.rating.typeAll') }}</option>
          <option value="bug">{{ t('market.rating.typeBug') }}</option>
          <option value="suggestion">{{ t('market.rating.typeSuggestion') }}</option>
          <option value="praise">{{ t('market.rating.typePraise') }}</option>
        </select>
      </div>
      <FeedbackList
        :items="feedbacks"
        :total="feedbackTotal"
        :page="feedbackPage"
        :page-size="feedbackPageSize"
        :labels="ratingLabels"
        @prev="loadFeedbacks(feedbackPage - 1)"
        @next="loadFeedbacks(feedbackPage + 1)"
      />
    </div>
  </div>
</template>
