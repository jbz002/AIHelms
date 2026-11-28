import { request } from './request'
import type {
  CreateMcpGrantParams,
  CreateMcpToolsetParams,
  GrantSubjectType,
  GrantTargetType,
  McpGrant,
  McpGrantListResult,
  McpGrantSyncResult,
  McpReconcileResult,
  McpToolset,
  McpToolsetListResult,
} from '../types/mcpAuthz'
import type { UpdateToolMetadataParams } from '../types/mcp'

export interface McpGrantFilters {
  subject_type?: GrantSubjectType
  subject_id?: number
  target_type?: GrantTargetType
  target_id?: number
  include_revoked?: boolean
}

export function listMcpGrants(filters: McpGrantFilters = {}): Promise<McpGrantListResult> {
  const params: Record<string, string | number | boolean> = {}
  if (filters.subject_type) params.subject_type = filters.subject_type
  if (filters.subject_id !== undefined) params.subject_id = filters.subject_id
  if (filters.target_type) params.target_type = filters.target_type
  if (filters.target_id !== undefined) params.target_id = filters.target_id
  if (filters.include_revoked) params.include_revoked = true
  return request<McpGrantListResult>('/api/v1/mcp/grants', { params })
}

export function createMcpGrant(
  params: CreateMcpGrantParams,
): Promise<{ grant: McpGrant; sync: McpGrantSyncResult }> {
  return request('/api/v1/mcp/grants', { method: 'POST', body: params })
}

export function revokeMcpGrant(grantId: number): Promise<{ sync: McpGrantSyncResult } | null> {
  return request(`/api/v1/mcp/grants/${grantId}`, { method: 'DELETE' })
}

export function listMcpToolsets(): Promise<McpToolsetListResult> {
  return request<McpToolsetListResult>('/api/v1/mcp/toolsets')
}

export function createMcpToolset(params: CreateMcpToolsetParams): Promise<McpToolset> {
  return request<McpToolset>('/api/v1/mcp/toolsets', { method: 'POST', body: params })
}

export function deleteMcpToolset(toolsetId: number): Promise<null> {
  return request<null>(`/api/v1/mcp/toolsets/${toolsetId}`, { method: 'DELETE' })
}

export function reconcileMcpAuthz(mode: 'check' | 'apply'): Promise<McpReconcileResult> {
  return request<McpReconcileResult>('/api/v1/mcp/reconcile', { method: 'POST', body: { mode } })
}

export function updateMcpToolMetadata(
  serverId: number,
  toolId: number,
  params: UpdateToolMetadataParams,
): Promise<{
  id: number
  tool_name: string
  risk_level: string
  data_classification: string
  review_status: string
  changes: string[]
}> {
  return request(`/api/v1/mcp/servers/${serverId}/tools/${toolId}/metadata`, {
    method: 'PUT',
    body: params,
  })
}
