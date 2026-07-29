export interface AdminMcpStatus {
  name: string
  endpoint_url: string
  transport: string
  auth_scheme: string
  tool_count: number
  tool_names: string[]
  has_active_api_key: boolean
}
