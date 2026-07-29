import { request } from './request'
import type { AdminMcpStatus } from '../types/admin-mcp'

export function getAdminMcpStatus(): Promise<AdminMcpStatus> {
  return request<AdminMcpStatus>('/api/v1/admin-mcp')
}
