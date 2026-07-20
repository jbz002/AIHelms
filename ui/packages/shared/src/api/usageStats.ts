import { request } from './request'
import type { McpUsageStats, SkillUsageStats, StatsRange } from '../types/usageStats'

export function getMcpUsageStats(serverId: number, days: StatsRange = 30): Promise<McpUsageStats> {
  return request<McpUsageStats>(`/api/v1/stats/mcp/${serverId}`, { params: { days } })
}

export function getSkillUsageStats(skillId: number, days: StatsRange = 30): Promise<SkillUsageStats> {
  return request<SkillUsageStats>(`/api/v1/stats/skill/${skillId}`, { params: { days } })
}
