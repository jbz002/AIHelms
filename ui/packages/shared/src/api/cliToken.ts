import { request } from './request'
import type {
  CliToken,
  CliTokenListResult,
  CreateCliTokenParams,
  UpdateCliTokenParams,
} from '../types/cliToken'

export function getCliTokens(
  page: number,
  pageSize: number,
  ownerId?: number,
): Promise<CliTokenListResult> {
  return request<CliTokenListResult>('/api/v1/cli-tokens', {
    params: { page, page_size: pageSize, owner_id: ownerId },
  })
}

export function getCliTokenById(id: number): Promise<CliToken> {
  return request<CliToken>(`/api/v1/cli-tokens/${id}`)
}

export function createCliToken(params: CreateCliTokenParams): Promise<CliToken> {
  return request<CliToken>('/api/v1/cli-tokens', {
    method: 'POST',
    body: params,
  })
}

export function updateCliToken(
  id: number,
  params: UpdateCliTokenParams,
): Promise<CliToken> {
  return request<CliToken>(`/api/v1/cli-tokens/${id}`, {
    method: 'PUT',
    body: params,
  })
}

export function toggleCliToken(id: number): Promise<CliToken> {
  return request<CliToken>(`/api/v1/cli-tokens/${id}/toggle`, {
    method: 'PUT',
  })
}

export function deleteCliToken(id: number): Promise<null> {
  return request<null>(`/api/v1/cli-tokens/${id}`, { method: 'DELETE' })
}
