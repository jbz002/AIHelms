import { request } from './request'
import { buildSkillFormData } from './skill'
import type { SkillFormFields } from './skill'
import type { Skill, SkillListResult, CreateSkillVersionParams, SkillVersion } from '../types/skill'
import type { McpServer, McpServerListResult, McpServerVersion } from '../types/mcp'
import type { Agent, AgentListResult } from '../types/agent'
import type { PublishReview } from '../types/publish-review'

const BASE = '/api/v1/contributor/skills'
const MCP_BASE = '/api/v1/contributor/mcps'
const AGENT_BASE = '/api/v1/contributor/agents'

export function getMyContributions(page: number = 1, pageSize: number = 20): Promise<SkillListResult> {
  return request<SkillListResult>(BASE, { params: { page, page_size: pageSize } })
}

export function getMyContribution(id: number): Promise<Skill> {
  return request<Skill>(`${BASE}/${id}`)
}

export function createContribution(fields: SkillFormFields): Promise<Skill> {
  return request<Skill>(BASE, { method: 'POST', body: buildSkillFormData(fields) })
}

export function updateContribution(id: number, fields: Partial<SkillFormFields>): Promise<Skill> {
  const fd = new FormData()
  if (fields.name !== undefined) fd.append('name', fields.name)
  if (fields.icon !== undefined) fd.append('icon', fields.icon)
  if (fields.icon_url !== undefined) fd.append('icon_url', fields.icon_url)
  if (fields.description !== undefined) fd.append('description', fields.description)
  if (fields.author !== undefined) fd.append('author', fields.author)
  if (fields.category !== undefined) fd.append('category', fields.category)
  if (fields.version !== undefined) fd.append('version', fields.version)
  if (fields.tags !== undefined) fd.append('tags', JSON.stringify(fields.tags))
  if (fields.usage_instructions !== undefined) fd.append('usage_instructions', fields.usage_instructions)
  return request<Skill>(`${BASE}/${id}`, { method: 'PUT', body: fd })
}

export function createContributionVersion(skillId: number, params: CreateSkillVersionParams): Promise<SkillVersion> {
  const fd = new FormData()
  fd.append('version', params.version)
  if (params.version_label !== undefined) fd.append('version_label', params.version_label)
  if (params.change_log !== undefined) fd.append('change_log', params.change_log)
  if (params.zip_file) fd.append('zip_file', params.zip_file)
  return request<SkillVersion>(`${BASE}/${skillId}/versions`, { method: 'POST', body: fd })
}

export function deleteContribution(id: number): Promise<null> {
  return request<null>(`${BASE}/${id}`, { method: 'DELETE' })
}

export function submitContributionReview(skillId: number): Promise<PublishReview> {
  return request<PublishReview>(`${BASE}/${skillId}/submit-review`, { method: 'POST' })
}

// ─── MCP Server 贡献（JSON body，无 zip） ────────────────────────────────────

export interface McpContributionFields {
  name: string
  server_name: string
  url: string
  transport: string
  auth_type?: string
  description?: string
  instructions?: string
  category?: string
  tags?: string[]
  author?: string
  icon_url?: string
  documentation_url?: string
  source_url?: string
}

export interface McpContributionVersionFields {
  version: string
  url: string
  transport: string
  change_log?: string
}

export function getMyMcpContributions(page: number = 1, pageSize: number = 20): Promise<McpServerListResult> {
  return request<McpServerListResult>(MCP_BASE, { params: { page, page_size: pageSize } })
}

export function getMyMcpContribution(id: number): Promise<McpServer> {
  return request<McpServer>(`${MCP_BASE}/${id}`)
}

export function createMcpContribution(fields: McpContributionFields): Promise<McpServer> {
  return request<McpServer>(MCP_BASE, { method: 'POST', body: fields })
}

export function updateMcpContribution(id: number, fields: Partial<McpContributionFields>): Promise<McpServer> {
  return request<McpServer>(`${MCP_BASE}/${id}`, { method: 'PUT', body: fields })
}

export function createMcpContributionVersion(serverId: number, fields: McpContributionVersionFields): Promise<McpServerVersion> {
  return request<McpServerVersion>(`${MCP_BASE}/${serverId}/versions`, { method: 'POST', body: fields })
}

export function deleteMcpContribution(id: number): Promise<null> {
  return request<null>(`${MCP_BASE}/${id}`, { method: 'DELETE' })
}

export function submitMcpReview(serverId: number): Promise<PublishReview> {
  return request<PublishReview>(`${MCP_BASE}/${serverId}/submit-review`, { method: 'POST' })
}

// ─── 智能体贡献（JSON body，无版本） ──────────────────────────────────────────

export interface AgentContributionFields {
  name: string
  platform: string
  icon?: string
  icon_url?: string
  description?: string
  category?: string
  chat_url?: string
  tags?: string[]
}

export function getMyAgentContributions(page: number = 1, pageSize: number = 20): Promise<AgentListResult> {
  return request<AgentListResult>(AGENT_BASE, { params: { page, page_size: pageSize } })
}

export function getMyAgentContribution(id: number): Promise<Agent> {
  return request<Agent>(`${AGENT_BASE}/${id}`)
}

export function createAgentContribution(fields: AgentContributionFields): Promise<Agent> {
  return request<Agent>(AGENT_BASE, { method: 'POST', body: fields })
}

export function updateAgentContribution(id: number, fields: Partial<AgentContributionFields>): Promise<Agent> {
  return request<Agent>(`${AGENT_BASE}/${id}`, { method: 'PUT', body: fields })
}

export function deleteAgentContribution(id: number): Promise<null> {
  return request<null>(`${AGENT_BASE}/${id}`, { method: 'DELETE' })
}

export function submitAgentReview(agentId: number): Promise<PublishReview> {
  return request<PublishReview>(`${AGENT_BASE}/${agentId}/submit-review`, { method: 'POST' })
}
