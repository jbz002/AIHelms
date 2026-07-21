export type PublishReviewEntityType = 'mcp_server' | 'skill' | 'custom_entity'
export type PublishReviewStatus = 'pending' | 'approved' | 'rejected' | 'withdrawn'

export interface PublishReview {
  id: number
  entity_type: PublishReviewEntityType
  entity_id: number
  requested_by: number | null
  status: PublishReviewStatus
  review_notes: string
  reviewed_by: number | null
  reviewed_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface PublishReviewListResult {
  items: PublishReview[]
  total: number
  page: number
  page_size: number
}

export interface SubmitPublishReviewParams {
  entity_type: PublishReviewEntityType
  entity_id: number
}

export interface PublishReviewActionParams {
  review_notes?: string
}

export interface PublishReviewQuery {
  status?: PublishReviewStatus
  entity_type?: PublishReviewEntityType
}
