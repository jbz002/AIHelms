/** P1 授权中心：授权矩阵 / 工具束 / 对账。 */

export type GrantSubjectType = 'user' | 'dept' | 'role' | 'public'
export type GrantTargetType = 'server' | 'toolset'
export type GrantEffect = 'allow' | 'deny'

export interface McpGrant {
  id: number
  subject_type: GrantSubjectType
  subject_id: number | null
  target_type: GrantTargetType
  target_id: number
  effect: GrantEffect
  expires_at: string | null
  granted_by: number | null
  reason: string | null
  revoked_at: string | null
  created_at: string | null
}

export interface CreateMcpGrantParams {
  subject_type: GrantSubjectType
  subject_id?: number | null
  target_type: GrantTargetType
  target_id: number
  effect?: GrantEffect
  expires_at?: string | null
  reason?: string
}

export interface McpGrantListResult {
  items: McpGrant[]
}

export interface McpToolsetItem {
  server_id: number
  tool_name: string
}

export interface McpToolset {
  id: number
  name: string
  description: string
  items: McpToolsetItem[]
  created_by: number | null
  created_at: string | null
}

export interface CreateMcpToolsetParams {
  name: string
  description?: string
  items: McpToolsetItem[]
}

export interface McpToolsetListResult {
  items: McpToolset[]
}

export interface McpReconcileItem {
  key_id: number
  added?: string[]
  removed?: string[]
  tools_expected?: Record<string, string[]>
  tools_actual?: Record<string, string[]>
  fixed?: boolean
  error?: string
  fix_error?: string
}

export interface McpReconcileResult {
  keys: number
  drift: number
  fixed: number
  errors: number
  items: McpReconcileItem[]
  mode: 'check' | 'apply'
}

/** 授权变更后的编译/下发回执（编译开关关闭时为 observe） */
export interface McpGrantSyncResult {
  mode: 'compiled' | 'observe'
  keys?: number
  applied?: number
  failed?: number
}
