import { request } from './request'
import type { PlatformSettings, UpdatePlatformSettingsParams } from '../types/platform-settings'

export function getPlatformSettings(): Promise<PlatformSettings> {
  return request<PlatformSettings>('/api/v1/platform-settings')
}

export function updatePlatformSettings(
  params: UpdatePlatformSettingsParams,
): Promise<PlatformSettings> {
  return request<PlatformSettings>('/api/v1/platform-settings', {
    method: 'PUT',
    body: params,
  })
}
