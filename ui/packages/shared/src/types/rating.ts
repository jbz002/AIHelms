export type EntityType = 'mcp_server' | 'skill'
export type FeedbackType = '' | 'bug' | 'suggestion' | 'praise'

export interface RatingView {
  avg_score: number
  rating_count: number
  last_rated_at: string | null
  my_score: number | null
  my_feedback_type: FeedbackType | null
  my_comment: string | null
  distribution: Record<number, number>
}

export interface RateParams {
  score: number
  feedback_type?: FeedbackType
  comment?: string
}

export interface RateResponse {
  my_score: number
  feedback_type: string
  avg_score: number
  rating_count: number
}

export interface FeedbackItem {
  user_id: number
  score: number
  feedback_type: FeedbackType
  comment: string
  updated_at: string
}

export interface FeedbackListResult {
  items: FeedbackItem[]
  total: number
  page: number
  page_size: number
}
