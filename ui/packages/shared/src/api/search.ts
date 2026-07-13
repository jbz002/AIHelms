import { request } from './request'
import type { SearchRequest, SearchResponse } from '../types/search'

export function search(
  params: SearchRequest,
  options?: { page?: number; page_size?: number },
): Promise<SearchResponse> {
  const body: Record<string, unknown> = { q: params.q }
  if (params.entity_types) {
    body.entity_types = params.entity_types
  }
  if (params.category) {
    body.category = params.category
  }
  return request<SearchResponse>('/api/v1/search', {
    method: 'POST',
    body,
    params: options
      ? { page: options.page, page_size: options.page_size }
      : undefined,
  })
}
