export interface SkillCategory {
  id: number
  name: string
  description: string
  sort_order: number
}

export interface Skill {
  id: number
  skill_id: string
  name: string
  icon: string
  description: string
  author: string
  category: string
  version: string
  tags: string[]
  agent_install_prompt: string
  usage_instructions: string
  zip_path: string
  zip_size: number
  zip_filename: string
  has_zip: boolean
  is_active: boolean
  is_published: boolean
  requires_approval: boolean
  visibility_type: string
  install_count: number
  avg_score?: number
  rating_count?: number
  frontmatter: Record<string, unknown>
  summary_text: string
  security_status?: 'not_scanned' | 'queued' | 'running' | 'completed' | 'failed'
  security_decision?: '' | 'passed' | 'attention_required' | 'high_risk' | 'failed'
  security_severity?:
    | ''
    | 'critical'
    | 'high'
    | 'medium'
    | 'low'
    | 'info'
    | 'none'
    | 'unknown'
  security_risk_score?: number
  latest_ai_policies_audit_id?: number | null
  latest_ai_policies_audit_code?: string | null
  source_type?: 'zip' | 'url' | null
  source_url?: string | null
  current_version_id?: number | null
  active_version?: SkillVersion | null
  created_by: number | null
  created_at: string | null
  updated_at: string | null
}

export type SkillVersionLifecycle = 'inactive' | 'active' | 'deprecated'

export interface ManifestFile {
  sha256: string
  size: number
  content_type?: string
  category?: 'root' | 'references' | 'scripts' | 'assets' | 'other' | string
}

export interface ProtocolIssue {
  severity: 'error' | 'warning'
  code: string
  message: string
}

export interface SkillVersion {
  id: number
  skill_id: number
  version: string
  version_label: string
  is_active: boolean
  lifecycle_status: SkillVersionLifecycle
  sunset_date: string | null
  source: 'manual' | 'auto_discovered'
  source_type: 'zip' | 'url'
  zip_size: number
  zip_filename: string
  change_log: string
  frontmatter: Record<string, unknown>
  summary_text: string
  composite_hash: string
  file_hashes: Record<string, ManifestFile>
  drift_detected: boolean
  drifted_files: string[]
  last_drift_check_at: string | null
  drift_check_error?: string
  protocol_valid: boolean
  protocol_errors: ProtocolIssue[]
  last_validated_at: string | null
  security_status?: 'not_scanned' | 'queued' | 'running' | 'completed' | 'failed'
  security_decision?: '' | 'passed' | 'attention_required' | 'high_risk' | 'failed'
  latest_ai_policies_audit_id?: number | null
  created_by: number | null
  created_at: string | null
}

export interface CreateSkillVersionParams {
  version: string
  version_label?: string
  change_log?: string
  zip_file?: File | null
}

export interface DeprecateSkillVersionParams {
  sunset_date?: string | null
}

export interface SkillListResult {
  items: Skill[]
  total: number
  page: number
  page_size: number
}

export interface CreateSkillCategoryParams {
  name: string
  description?: string
  sort_order?: number
}

export interface SkillSummaryView {
  id: number
  name: string
  frontmatter: Record<string, unknown>
  summary_text: string
}

export interface SkillFullView {
  id: number
  name: string
  frontmatter: Record<string, unknown>
  summary_text: string
  full_content: string
  file_hashes: Record<string, ManifestFile>
  composite_hash: string
}

export interface SkillIntegrityView {
  skill_id: number
  version_id: number | null
  version: string
  source_type: string
  composite_hash: string
  content_sha256: string
  file_hashes: Record<string, ManifestFile>
  drift_detected: boolean
  drifted_files: string[]
  last_drift_check_at: string | null
  drift_check_error?: string
  protocol_valid: boolean
  protocol_errors: ProtocolIssue[]
}
