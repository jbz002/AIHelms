export interface McpCategory {
  id: number
  name: string
  description: string
  sort_order: number
}

export interface CreateMcpCategoryParams {
  name: string
  description?: string
  sort_order?: number
}

export interface McpServer {
  id: number
  server_id: string
  name: string
  server_name: string
  description: string
  url: string
  transport: string
  auth_type: string
  credentials?: Record<string, unknown>
  instructions: string
  mcp_info: Record<string, unknown>
  extra_headers: string[]
  allowed_tools: string[]
  authorization_url: string | null
  token_url: string | null
  registration_url: string | null
  category: string
  tags: string[]
  author: string
  icon_url: string
  documentation_url: string
  source_url: string
  billing_type: string
  internal_cost_per_call: number
  external_cost_per_call: number
  is_active: boolean
  is_published: boolean
  visibility_type: string
  visible_department_id?: number | null
  requires_approval: boolean
  status: string
  call_count: number
  last_health_check: string | null
  health_check_error: string | null
  litellm_synced: boolean
  litellm_sync_error: string | null
  /** false = 仅目录登记：市场可见但数据面不经 LiteLLM（按人 OAuth 类） */
  sync_to_litellm: boolean
  /** true = 网关 allow_all_keys（全员可用），仅限只读目录类 */
  is_public: boolean
  /** 置公共的理由（审计） */
  public_reason: string | null
  current_version_id: number | null
  active_version: McpServerVersion | null
  created_by: number | null
  created_at: string | null
  updated_at: string | null
  tools?: McpTool[]
}

export type McpVersionLifecycle = 'inactive' | 'active' | 'deprecated'

export interface McpServerVersion {
  id: number
  server_id: number
  version: string
  version_label: string
  is_active: boolean
  lifecycle_status: McpVersionLifecycle
  sunset_date: string | null
  source: 'manual' | 'auto_discovered'
  url: string
  transport: string
  auth_type: string
  change_log: string
  auto_discovered_version: string
  created_by: number | null
  created_at: string | null
}

export interface CreateMcpVersionParams {
  version: string
  version_label?: string
  url: string
  transport: string
  auth_type?: string
  credentials?: Record<string, unknown>
  mcp_info?: Record<string, unknown>
  allowed_tools?: string[]
  extra_headers?: string[]
  instructions?: string
  change_log?: string
}

export interface DeprecateMcpVersionParams {
  sunset_date?: string | null
}

export interface McpTool {
  id: number
  server_id: number
  tool_name: string
  namespaced_name: string
  display_name: string
  description: string
  input_schema: Record<string, unknown>
  billing_type: string | null
  internal_cost_per_call: number | null
  external_cost_per_call: number | null
  is_active: boolean
  // ── P1 授权中心：工具是可授权资源 ──
  tool_key: string | null
  risk_level: 'read' | 'write' | 'sensitive' | 'destructive'
  data_classification: 'public' | 'internal' | 'confidential' | 'secret'
  permission_key: string | null
  annotations: Record<string, unknown> | null
  output_schema: Record<string, unknown> | null
  fields_allowlist: string[] | null
  schema_hash: string | null
  review_status: 'pending' | 'approved' | 'rejected'
  reviewed_by: number | null
  reviewed_at: string | null
}

export interface McpServerListResult {
  items: McpServer[]
  total: number
  page: number
  page_size: number
}

export interface CreateMcpServerParams {
  name: string
  server_name: string
  url: string
  transport?: string
  auth_type?: string
  credentials?: Record<string, unknown>
  description?: string
  instructions?: string
  mcp_info?: Record<string, unknown>
  extra_headers?: string[]
  allowed_tools?: string[]
  authorization_url?: string
  token_url?: string
  registration_url?: string
  category?: string
  tags?: string[]
  author?: string
  icon_url?: string
  documentation_url?: string
  source_url?: string
  billing_type?: string
  internal_cost_per_call?: number
  external_cost_per_call?: number
  is_published?: boolean
  visibility_type?: string
  visible_department_id?: number
  requires_approval?: boolean
  is_public?: boolean
  public_reason?: string | null
}

export interface UpdateMcpServerParams {
  name?: string
  server_name?: string
  url?: string
  transport?: string
  auth_type?: string
  credentials?: Record<string, unknown>
  description?: string
  instructions?: string
  mcp_info?: Record<string, unknown>
  extra_headers?: string[]
  allowed_tools?: string[]
  authorization_url?: string
  token_url?: string
  registration_url?: string
  category?: string
  tags?: string[]
  author?: string
  icon_url?: string
  documentation_url?: string
  source_url?: string
  billing_type?: string
  internal_cost_per_call?: number
  external_cost_per_call?: number
  is_active?: boolean
  is_published?: boolean
  visibility_type?: string
  visible_department_id?: number
  requires_approval?: boolean
  is_public?: boolean
  public_reason?: string | null
}

export interface UpdateToolBillingParams {
  billing_type?: string
  internal_cost_per_call?: number
  external_cost_per_call?: number
}

/** P1 工具授权元数据（风险级 / 数据分级 / 字段白名单 / 审核状态） */
export interface UpdateToolMetadataParams {
  risk_level?: 'read' | 'write' | 'sensitive' | 'destructive'
  data_classification?: 'public' | 'internal' | 'confidential' | 'secret'
  permission_key?: string | null
  fields_allowlist?: string[] | null
  annotations?: Record<string, unknown> | null
  review_status?: 'pending' | 'approved' | 'rejected'
}
