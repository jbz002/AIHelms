export interface MatchContext {
  matched_fields: string[]
  matched_text: string
}

export interface SearchResultItem {
  entity_type: string
  entity_id: number
  name: string
  description: string
  relevance_score: number
  match_context: MatchContext
  metadata: Record<string, unknown>
}

export interface SearchResponse {
  items: SearchResultItem[]
  total: number
  page: number
  page_size: number
}

export interface SearchRequest {
  q: string
  entity_types?: string[]
  category?: string
}
