export type StatsRange = 7 | 30 | 90

export interface UsageTrendPoint {
  date: string
  count: number
}

export interface ToolDistItem {
  tool_name: string
  count: number
}

export interface ActionDistItem {
  action: string
  count: number
}

export interface McpUsageStats {
  total_calls: number
  unique_users: number
  total_cost: number
  avg_duration_ms: number
  trend: UsageTrendPoint[]
  tool_distribution: ToolDistItem[]
}

export interface SkillUsageStats {
  total_downloads: number
  unique_users: number
  agent_downloads: number
  manual_downloads: number
  trend: UsageTrendPoint[]
  action_distribution: ActionDistItem[]
}
