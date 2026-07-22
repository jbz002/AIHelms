/** CLI 令牌可选 scope（skill:* 为通配）。 */
export const CLI_SCOPE_OPTIONS = [
  'skill:search',
  'skill:read',
  'skill:install',
  'skill:tag:read',
  'skill:label:read',
  'skill:*',
] as const

export type CliScope = (typeof CLI_SCOPE_OPTIONS)[number]

export interface CliToken {
  id: number
  name: string
  description: string
  token_kind: string
  token_prefix: string
  scopes: string[]
  owner_type: string
  owner_id: number
  is_active: boolean
  created_by: number | null
  created_at: string
  updated_at: string
  expires_at: string | null
  last_used_at: string | null
  /** 仅创建时返回一次的完整 token。 */
  key_value?: string
}

export interface CliTokenListResult {
  items: CliToken[]
  total: number
  page: number
  page_size: number
}

export interface CreateCliTokenParams {
  name: string
  description?: string
  scopes: string[]
  owner_id: number
  owner_type?: string
  expires_at?: string | null
}

export interface UpdateCliTokenParams {
  name?: string
  description?: string
  scopes?: string[]
  is_active?: boolean
}
