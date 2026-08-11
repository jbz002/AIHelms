export interface ModelInfo {
  id: number
  name: string
  model_id: string
  category: string
  mode?: string | null
  capabilities: string[]
  description: string
  logo_provider_type: string
  icon_url: string
  is_active: boolean
  is_published: boolean
  visibility_type: string
  max_input_tokens?: number | null
  max_output_tokens?: number | null
  supports_vision?: boolean
  supports_function_calling?: boolean
  supports_reasoning?: boolean
  supports_response_schema?: boolean
  supports_parallel_function_calling?: boolean
  supports_tool_choice?: boolean
  litellm_provider?: string
  deprecation_date?: string | null
  registry_rpm?: number | null
  registry_tpm?: number | null
  deployment_count: number
  created_at: string | null
  updated_at: string | null
  deployments?: Deployment[]
}

export interface Deployment {
  id: number
  model_id: number
  credential_id: number | null
  credential_name: string | null
  litellm_model_id: string | null
  litellm_params: Record<string, unknown>
  model_info: Record<string, unknown>
  deploy_name: string
  billing_type: string
  cost_per_call: string | null
  monthly_call_quota: number | null
  monthly_call_used: number
  is_active: boolean
  created_at: string | null
}

export interface CreateModelParams {
  name: string
  model_id?: string
  category?: string
  mode?: string | null
  capabilities?: string[]
  description?: string
  logo_provider_type?: string
  max_input_tokens?: number | null
  max_output_tokens?: number | null
  supports_vision?: boolean
  supports_function_calling?: boolean
  supports_reasoning?: boolean
  supports_response_schema?: boolean
  supports_parallel_function_calling?: boolean
  supports_tool_choice?: boolean
  litellm_provider?: string
  deprecation_date?: string | null
  registry_rpm?: number | null
  registry_tpm?: number | null
}

export interface UpdateModelParams {
  name?: string
  model_id?: string
  category?: string
  mode?: string | null
  capabilities?: string[]
  description?: string
  logo_provider_type?: string
  is_active?: boolean
  max_input_tokens?: number | null
  max_output_tokens?: number | null
  supports_vision?: boolean
  supports_function_calling?: boolean
  supports_reasoning?: boolean
  supports_response_schema?: boolean
  supports_parallel_function_calling?: boolean
  supports_tool_choice?: boolean
  litellm_provider?: string
  deprecation_date?: string | null
  registry_rpm?: number | null
  registry_tpm?: number | null
}

export interface CreateDeploymentParams {
  litellm_params: Record<string, unknown>
  credential_id?: number | null
  deploy_name?: string
  billing_type?: string
  cost_per_call?: number | null
  monthly_call_quota?: number | null
  model_info?: Record<string, unknown> | null
  model_id_str?: string
}

export interface UpdateDeploymentParams {
  litellm_params?: Record<string, unknown>
  credential_id?: number | null
  deploy_name?: string
  billing_type?: string
  cost_per_call?: number | null
  monthly_call_quota?: number | null
  model_info?: Record<string, unknown> | null
  is_active?: boolean
}

export interface ModelListResult {
  items: ModelInfo[]
  total: number
  page: number
  page_size: number
}

export interface ActiveModel {
  id: number
  name: string
  model_id: string
  category?: string
  mode?: string | null
  capabilities?: string[]
  description?: string
  logo_provider_type: string
  icon_url: string
  is_published?: boolean
  requires_approval?: boolean
  has_anthropic_deployment?: boolean
  has_openai_deployment?: boolean
  max_input_tokens?: number | null
  max_output_tokens?: number | null
  supports_vision?: boolean
  supports_function_calling?: boolean
  supports_reasoning?: boolean
  supports_response_schema?: boolean
  supports_parallel_function_calling?: boolean
  supports_tool_choice?: boolean
  litellm_provider?: string
  deprecation_date?: string | null
  registry_rpm?: number | null
  registry_tpm?: number | null
}

export interface RegistryEntry {
  model_name: string
  litellm_provider?: string
  mode?: string
  max_tokens?: number
  max_input_tokens?: number
  max_output_tokens?: number
  supports_vision?: boolean
  supports_function_calling?: boolean
  supports_parallel_function_calling?: boolean
  supports_reasoning?: boolean
  supports_response_schema?: boolean
  supports_tool_choice?: boolean
  supports_system_messages?: boolean
  supports_prompt_caching?: boolean
  supports_pdf_input?: boolean
  supports_web_search?: boolean
  supports_audio_input?: boolean
  supports_audio_output?: boolean
  deprecation_date?: string
  /** 注册表声明的模型支持端点（如 /v1/chat/completions），仅展示不入库 */
  supported_endpoints?: string[]
  /** 注册表声明的 provider 对该模型的速率硬限（RPM/TPM），只读快照 */
  rpm?: number
  tpm?: number
  input_cost_per_token?: number
  output_cost_per_token?: number
  cache_read_input_token_cost?: number
  cache_creation_input_token_cost?: number
  output_cost_per_reasoning_token?: number
  /** 后端按 usd_to_cny_rate 折算后的 ¥/百万token（registry-lookup 附加，部署定价回填用） */
  input_cost_per_million_tokens_cny?: number | null
  output_cost_per_million_tokens_cny?: number | null
  cache_read_input_cost_per_million_tokens_cny?: number | null
  cache_creation_input_cost_per_million_tokens_cny?: number | null
  output_cost_per_reasoning_token_per_million_tokens_cny?: number | null
}

export interface AccessGroup {
  id: number
  group_name: string
  description: string
  model_ids: string[]
  is_active: boolean
  created_at: string | null
}

export interface CreateAccessGroupParams {
  group_name: string
  description?: string
  model_ids?: string[]
}

export interface UpdateAccessGroupParams {
  group_name?: string
  description?: string
  model_ids?: string[]
  is_active?: boolean
}

export interface RouterSettings {
  id?: number
  routing_strategy: string
  fallbacks: unknown[]
  allowed_fails: number
  cooldown_time: number
  num_retries: number
  timeout: number
  config: Record<string, unknown>
  updated_at?: string | null
}

export interface UpdateRouterSettingsParams {
  routing_strategy?: string
  fallbacks?: unknown[]
  allowed_fails?: number
  cooldown_time?: number
  num_retries?: number
  timeout?: number
  config?: Record<string, unknown>
}

export interface ModelVisibility {
  is_published: boolean
  visibility_type: string
  requires_approval: boolean
  department_ids: number[]
  departments: { id: number; name: string }[]
  user_ids: number[]
  user_count: number
}

export interface UpdateModelPublishParams {
  is_published?: boolean
  visibility_type?: string
  department_ids?: number[]
  requires_approval?: boolean
}

export interface ResyncAnthropicResult {
  deployments_synced: number
  deployment_errors: number
  keys_updated: number
}
