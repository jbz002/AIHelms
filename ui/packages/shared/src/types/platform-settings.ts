export interface PlatformSettings {
  default_model_id: number | null
  default_model_name: string | null
  env_default_model_id: number | null
  default_key_budget_limit: string | null
  default_key_budget_hard_limit: boolean
  default_key_budget_duration: string | null
  default_key_rate_limit_mode: 'none' | 'total'
  default_key_tpm_limit: number | null
  default_key_rpm_limit: number | null
  default_key_max_parallel_requests: number | null
  updated_by: number | null
  updated_at: string | null
}

export interface UpdatePlatformSettingsParams {
  default_model_id: number | null
  default_key_budget_limit: number | null
  default_key_budget_hard_limit: boolean
  default_key_budget_duration: string
  default_key_rate_limit_mode: 'none' | 'total'
  default_key_tpm_limit: number | null
  default_key_rpm_limit: number | null
  default_key_max_parallel_requests: number | null
}
