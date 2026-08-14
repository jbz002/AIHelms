import { request } from './request'
import type {
  Provider,
  ProviderListResult,
  CreateProviderParams,
  UpdateProviderParams,
} from '../types/provider'
import type { ResolvedPrefix } from '../types/model'

export function getProviders(page: number = 1, pageSize: number = 50): Promise<ProviderListResult> {
  return request<ProviderListResult>('/api/v1/providers', { params: { page, page_size: pageSize } })
}

export function getProviderById(id: number): Promise<Provider> {
  return request<Provider>(`/api/v1/providers/${id}`)
}

export function createProvider(params: CreateProviderParams): Promise<Provider> {
  return request<Provider>('/api/v1/providers', { method: 'POST', body: params })
}

export function updateProvider(id: number, params: UpdateProviderParams): Promise<Provider> {
  return request<Provider>(`/api/v1/providers/${id}`, { method: 'PUT', body: params })
}

export function deleteProvider(id: number): Promise<null> {
  return request<null>(`/api/v1/providers/${id}`, { method: 'DELETE' })
}

/** 查询供应商在 (format, category) 下解析出的最终 LiteLLM 前缀及来源 */
export function resolveProviderPrefix(
  providerId: number,
  format: string = 'openai',
  category: string = 'chat',
): Promise<ResolvedPrefix> {
  return request<ResolvedPrefix>(`/api/v1/providers/${providerId}/resolved-prefix`, {
    params: { format, category },
  })
}
