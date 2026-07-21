export interface PublishSettings {
  publish_review_enabled: boolean
  updated_by: number | null
  updated_at: string | null
}

export interface UpdatePublishSettingsParams {
  enabled: boolean
}
