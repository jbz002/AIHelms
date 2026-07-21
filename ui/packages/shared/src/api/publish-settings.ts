import { request } from './request'
import type { PublishSettings, UpdatePublishSettingsParams } from '../types/publish-settings'

export function getPublishSettings(): Promise<PublishSettings> {
  return request<PublishSettings>('/api/v1/publish-settings')
}

export function updatePublishSettings(
  params: UpdatePublishSettingsParams,
): Promise<PublishSettings> {
  return request<PublishSettings>('/api/v1/publish-settings', {
    method: 'PUT',
    body: params,
  })
}
