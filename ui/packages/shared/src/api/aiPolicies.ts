import { request } from './request'
import type {
  AiPolicyAudit,
  AiPolicyAuditHistoryItem,
  AiPolicyAuditListResult,
  AiPolicyAuditQuery,
  AiPolicyPreset,
  AiPolicyRiskCatalogItem,
  AiPolicySettings,
  AiPolicySignatureRules,
} from '../types/aiPolicies'

export function getAiPolicyAudits(params: AiPolicyAuditQuery = {}): Promise<AiPolicyAuditListResult> {
  return request<AiPolicyAuditListResult>('/api/v1/ai-policies/audits', {
    params: params as Record<string, string | number | boolean | undefined>,
  })
}

export function getAiPolicyAudit(
  auditId: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<AiPolicyAudit> {
  return request<AiPolicyAudit>(`/api/v1/ai-policies/audits/${auditId}`, { params })
}

export function getAiPolicyReportDownloadUrl(auditId: string): string {
  return `/api/v1/ai-policies/audits/${auditId}/download`
}

export function getAiPolicyRiskCatalog(): Promise<AiPolicyRiskCatalogItem[]> {
  return request<AiPolicyRiskCatalogItem[]>('/api/v1/ai-policies/catalog')
}

export function getAiPolicySettings(): Promise<AiPolicySettings> {
  return request<AiPolicySettings>('/api/v1/ai-policies/settings')
}

export interface UpdateAiPolicySettingsParams {
  llm_review_enabled: boolean
  default_policy?: string
  policy_overrides?: Record<string, string>
  llm_consensus_runs?: number
  regex_enabled?: boolean
}

export function updateAiPolicySettings(params: UpdateAiPolicySettingsParams): Promise<AiPolicySettings> {
  return request<AiPolicySettings>('/api/v1/ai-policies/settings', { method: 'PUT', body: params })
}

export function getAiPolicyPolicies(): Promise<AiPolicyPreset[]> {
  return request<AiPolicyPreset[]>('/api/v1/ai-policies/policies')
}

export function getAiPolicySignatures(): Promise<AiPolicySignatureRules> {
  return request<AiPolicySignatureRules>('/api/v1/ai-policies/rules/signatures')
}

export function replaceAiPolicySignatures(content: string): Promise<AiPolicySignatureRules> {
  return request<AiPolicySignatureRules>('/api/v1/ai-policies/rules/signatures', {
    method: 'PUT',
    body: { content },
  })
}

export function getVersionAuditHistory(
  skillId: number,
  versionId: number,
  params: { page?: number; page_size?: number } = {},
): Promise<{ items: AiPolicyAuditHistoryItem[]; total: number; page: number; page_size: number }> {
  return request(`/api/v1/ai-policies/skills/${skillId}/versions/${versionId}/audit-history`, {
    params: params as Record<string, string | number | boolean | undefined>,
  })
}
