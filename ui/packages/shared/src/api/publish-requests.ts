import { request } from './request'
import type {
  PublishReview,
  PublishReviewListResult,
  SubmitPublishReviewParams,
  PublishReviewActionParams,
  PublishReviewQuery,
} from '../types/publish-review'

export function getPublishReviews(
  page: number = 1,
  pageSize: number = 20,
  query: PublishReviewQuery = {},
): Promise<PublishReviewListResult> {
  const params: Record<string, string | number> = { page, page_size: pageSize }
  if (query.status) params.status = query.status
  if (query.entity_type) params.entity_type = query.entity_type
  return request<PublishReviewListResult>('/api/v1/publish-requests', { params })
}

export function getPublishReviewById(id: number): Promise<PublishReview> {
  return request<PublishReview>(`/api/v1/publish-requests/${id}`)
}

export function submitPublishReview(
  params: SubmitPublishReviewParams,
): Promise<PublishReview> {
  return request<PublishReview>('/api/v1/publish-requests', {
    method: 'POST',
    body: params,
  })
}

export function approvePublishReview(
  id: number,
  params: PublishReviewActionParams = {},
): Promise<PublishReview> {
  return request<PublishReview>(`/api/v1/publish-requests/${id}/approve`, {
    method: 'PUT',
    body: params,
  })
}

export function rejectPublishReview(
  id: number,
  params: PublishReviewActionParams = {},
): Promise<PublishReview> {
  return request<PublishReview>(`/api/v1/publish-requests/${id}/reject`, {
    method: 'PUT',
    body: params,
  })
}

export function withdrawPublishReview(id: number): Promise<PublishReview> {
  return request<PublishReview>(`/api/v1/publish-requests/${id}/withdraw`, {
    method: 'PUT',
  })
}
