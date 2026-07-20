import { request } from './request'
import type { EntityType, FeedbackListResult, RateParams, RateResponse, RatingView } from '../types/rating'

export function getRating(
  entityType: EntityType,
  entityId: number,
): Promise<RatingView> {
  return request<RatingView>(`/api/v1/ratings/${entityType}/${entityId}`)
}

export function rateResource(
  entityType: EntityType,
  entityId: number,
  params: RateParams,
): Promise<RateResponse> {
  return request<RateResponse>(`/api/v1/ratings/${entityType}/${entityId}`, {
    method: 'POST',
    body: params,
  })
}

export function listFeedbacks(
  entityType: EntityType,
  entityId: number,
  page: number = 1,
  pageSize: number = 20,
  feedbackType?: string,
): Promise<FeedbackListResult> {
  const params: Record<string, string | number | boolean | undefined> = {
    page,
    page_size: pageSize,
  }
  if (feedbackType) params.feedback_type = feedbackType
  return request<FeedbackListResult>(`/api/v1/ratings/${entityType}/${entityId}/feedbacks`, {
    params,
  })
}
