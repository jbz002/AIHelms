export interface PlatformSettings {
  default_model_id: number | null
  default_model_name: string | null
  env_default_model_id: number | null
  updated_by: number | null
  updated_at: string | null
}

export interface UpdatePlatformSettingsParams {
  default_model_id: number | null
}
