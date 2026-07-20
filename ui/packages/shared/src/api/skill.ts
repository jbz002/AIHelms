import { request } from './request'
import type {
  Skill,
  SkillCategory,
  SkillListResult,
  CreateSkillCategoryParams,
  SkillVersion,
  CreateSkillVersionParams,
  DeprecateSkillVersionParams,
  SkillSummaryView,
  SkillFullView,
  SkillIntegrityView,
} from '../types/skill'
import type { AiPolicyAudit } from '../types/aiPolicies'

export function getSkills(
  page: number = 1,
  pageSize: number = 50,
  category?: string,
  isPublished?: boolean,
): Promise<SkillListResult> {
  const params: Record<string, string | number | boolean> = { page, page_size: pageSize }
  if (category) params.category = category
  if (isPublished !== undefined) params.is_published = isPublished
  return request<SkillListResult>('/api/v1/skills', { params })
}

export function getSkillById(id: number): Promise<Skill> {
  return request<Skill>(`/api/v1/skills/${id}`)
}

interface SkillFormFields {
  name: string
  icon?: string
  description?: string
  author?: string
  category?: string
  version?: string
  tags?: string[]
  usage_instructions?: string
  is_published?: boolean
  requires_approval?: boolean
  zip_file?: File | null
  source_url?: string
}

function buildSkillFormData(fields: SkillFormFields): FormData {
  const fd = new FormData()
  fd.append('name', fields.name)
  if (fields.icon !== undefined) fd.append('icon', fields.icon)
  if (fields.description !== undefined) fd.append('description', fields.description)
  if (fields.author !== undefined) fd.append('author', fields.author)
  if (fields.category !== undefined) fd.append('category', fields.category)
  if (fields.version !== undefined) fd.append('version', fields.version)
  fd.append('tags', JSON.stringify(fields.tags ?? []))
  if (fields.usage_instructions !== undefined) fd.append('usage_instructions', fields.usage_instructions)
  if (fields.is_published !== undefined) fd.append('is_published', String(fields.is_published))
  if (fields.requires_approval !== undefined) fd.append('requires_approval', String(fields.requires_approval))
  if (fields.zip_file) fd.append('zip_file', fields.zip_file)
  if (fields.source_url) fd.append('source_url', fields.source_url)
  return fd
}

export function createSkill(fields: SkillFormFields): Promise<Skill> {
  return request<Skill>('/api/v1/skills', { method: 'POST', body: buildSkillFormData(fields) })
}

export function updateSkill(id: number, fields: Partial<SkillFormFields>): Promise<Skill> {
  const fd = new FormData()
  if (fields.name !== undefined) fd.append('name', fields.name)
  if (fields.icon !== undefined) fd.append('icon', fields.icon)
  if (fields.description !== undefined) fd.append('description', fields.description)
  if (fields.author !== undefined) fd.append('author', fields.author)
  if (fields.category !== undefined) fd.append('category', fields.category)
  if (fields.version !== undefined) fd.append('version', fields.version)
  if (fields.tags !== undefined) fd.append('tags', JSON.stringify(fields.tags))
  if (fields.usage_instructions !== undefined) fd.append('usage_instructions', fields.usage_instructions)
  if (fields.is_published !== undefined) fd.append('is_published', String(fields.is_published))
  if (fields.requires_approval !== undefined) fd.append('requires_approval', String(fields.requires_approval))
  if (fields.zip_file) fd.append('zip_file', fields.zip_file)
  return request<Skill>(`/api/v1/skills/${id}`, { method: 'PUT', body: fd })
}

export function deleteSkill(id: number): Promise<null> {
  return request<null>(`/api/v1/skills/${id}`, { method: 'DELETE' })
}

export function createSkillSecurityAudit(id: number): Promise<AiPolicyAudit> {
  return request<AiPolicyAudit>(`/api/v1/skills/${id}/ai-policies-audits`, { method: 'POST' })
}

export function getSkillVersions(skillId: number, includeDeprecated: boolean = true): Promise<SkillVersion[]> {
  const params: Record<string, string | number | boolean> = { include_deprecated: includeDeprecated }
  return request<SkillVersion[]>(`/api/v1/skills/${skillId}/versions`, { params })
}

export function createSkillVersion(skillId: number, params: CreateSkillVersionParams): Promise<SkillVersion> {
  const fd = new FormData()
  fd.append('version', params.version)
  if (params.version_label !== undefined) fd.append('version_label', params.version_label)
  if (params.change_log !== undefined) fd.append('change_log', params.change_log)
  if (params.zip_file) fd.append('zip_file', params.zip_file)
  return request<SkillVersion>(`/api/v1/skills/${skillId}/versions`, { method: 'POST', body: fd })
}

export function activateSkillVersion(skillId: number, versionId: number): Promise<Skill> {
  return request<Skill>(`/api/v1/skills/${skillId}/versions/${versionId}/activate`, { method: 'POST' })
}

export function deprecateSkillVersion(
  skillId: number,
  versionId: number,
  params: DeprecateSkillVersionParams = {},
): Promise<SkillVersion> {
  return request<SkillVersion>(`/api/v1/skills/${skillId}/versions/${versionId}/deprecate`, {
    method: 'POST',
    body: params,
  })
}

export function createSkillVersionSecurityAudit(skillId: number, versionId: number): Promise<AiPolicyAudit> {
  return request<AiPolicyAudit>(
    `/api/v1/skills/${skillId}/versions/${versionId}/ai-policies-audits`,
    { method: 'POST' },
  )
}

export function getSkillDownloadUrl(id: number): string {
  return `/api/v1/skills/${id}/download`
}

export function getSkillCategories(): Promise<SkillCategory[]> {
  return request<SkillCategory[]>('/api/v1/skills/categories')
}

export function createSkillCategory(params: CreateSkillCategoryParams): Promise<SkillCategory> {
  return request<SkillCategory>('/api/v1/skills/categories', { method: 'POST', body: params })
}

export function deleteSkillCategory(id: number): Promise<null> {
  return request<null>(`/api/v1/skills/categories/${id}`, { method: 'DELETE' })
}

export function getSkillSummary(skillId: number): Promise<SkillSummaryView> {
  return request<SkillSummaryView>(`/api/v1/skills/${skillId}/summary`)
}

export function getSkillFull(skillId: number): Promise<SkillFullView> {
  return request<SkillFullView>(`/api/v1/skills/${skillId}/full`)
}

export function getSkillIntegrity(skillId: number): Promise<SkillIntegrityView> {
  return request<SkillIntegrityView>(`/api/v1/skills/${skillId}/integrity`)
}
