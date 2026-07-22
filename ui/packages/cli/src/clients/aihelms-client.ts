import { EXIT } from '../shared/constants'
import { CliError } from '../shared/errors'

export interface WhoAmIResponse {
  owner_id: number
  owner_type: string
  scopes: string[]
}

export interface SkillSearchItem {
  id: number
  skill_id: string
  name: string
  icon: string
  description: string
  version: string
  category: string
  author: string
  install_count: number | null
  labels: string[]
}

export interface SkillSearchResponse {
  items: SkillSearchItem[]
  total: number
  page: number
  page_size: number
}

export interface SkillDetail {
  id: number
  name: string
  skill_id: string
  frontmatter: Record<string, unknown>
  summary_text: string
  full_content: string
  file_hashes: Record<string, unknown>
  composite_hash: string
  category: string
  icon: string
  author: string
  install_count: number | null
}

export interface SkillVersion {
  id: number
  version: string
  version_label: string
  is_active: boolean
  lifecycle_status: string
  sunset_date: string | null
  source: string
  source_type: string
  zip_size: number | null
  zip_filename: string | null
  change_log: string | null
  created_at: string | null
}

export interface SkillTag {
  id: number
  tag_name: string
  version_id: number
  is_system: boolean
  created_at: string | null
}

export interface SkillLabel {
  id: number
  label_id: number
  name: string
  display_name_key: string
  color: string
  sort_order: number
  granted_at: string | null
  note: string
}

export interface PublishVersionFields {
  version: string
  version_label?: string
  change_log?: string
}

interface Envelope<T> {
  code: number
  message: string
  data: T
}

export class AihelmsClient {
  constructor(
    readonly registry: string,
    readonly token?: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async whoami(): Promise<WhoAmIResponse> {
    return this.getJson('/auth/whoami')
  }

  async search(
    query: string,
    opts: { category?: string; label?: string; sort?: string; limit?: number } = {},
  ): Promise<SkillSearchResponse> {
    const params = new URLSearchParams()
    if (query) params.set('q', query)
    if (opts.category) params.set('category', opts.category)
    if (opts.label) params.set('label', opts.label)
    if (opts.sort) params.set('sort', opts.sort)
    params.set('page_size', String(opts.limit ?? 20))
    return this.getJson(`/skills?${params}`)
  }

  async getSkill(skillId: string): Promise<SkillDetail> {
    return this.getJson(`/skills/${skillId}`)
  }

  async listVersions(skillId: string): Promise<SkillVersion[]> {
    return this.getJson(`/skills/${skillId}/versions`)
  }

  async listTags(skillId: string): Promise<SkillTag[]> {
    return this.getJson(`/skills/${skillId}/tags`)
  }

  async listLabels(skillId: string): Promise<SkillLabel[]> {
    return this.getJson(`/skills/${skillId}/labels`)
  }

  async download(skillId: string, version?: string): Promise<Response> {
    const url = version
      ? `${this.registry}/api/v1/cli/skills/${skillId}/download?version=${encodeURIComponent(version)}`
      : `${this.registry}/api/v1/cli/skills/${skillId}/download`
    let response: Response
    try {
      response = await this.fetchImpl(url, { headers: this.headers() })
    } catch {
      throw new CliError('registry unreachable', EXIT.network, {
        registry: this.registry,
        next: 'check network or pass --registry',
      })
    }
    if (response.status === 401) {
      throw new CliError('authentication failed', EXIT.auth, {
        registry: this.registry,
        next: 'run `aihelms login`',
      })
    }
    if (response.status === 403) {
      const detail = await this.readDetail(response)
      throw new CliError(detail || 'access denied — token may lack skill:install scope', EXIT.auth, {
        registry: this.registry,
        next: detail ? '该 Skill 需审批，请通过 web 端申请' : 'regenerate token with required scopes',
      })
    }
    if (response.status === 404) {
      throw new CliError('skill or version not found', EXIT.generic, { registry: this.registry })
    }
    if (!response.ok) {
      const detail = await this.readDetail(response)
      throw new CliError(detail || `download failed with status ${response.status}`, EXIT.generic, {
        registry: this.registry,
      })
    }
    return response
  }

  async publishVersion(
    skillId: string,
    file: Blob,
    fields: PublishVersionFields,
    fileName = 'skill.zip',
  ): Promise<{ version: SkillVersion; review_task: Record<string, unknown> }> {
    const formData = new FormData()
    formData.append('zip_file', file, fileName)
    formData.append('version', fields.version)
    formData.append('version_label', fields.version_label ?? '')
    formData.append('change_log', fields.change_log ?? '')

    let response: Response
    try {
      response = await this.fetchImpl(`${this.registry}/api/v1/cli/skills/${skillId}/versions`, {
        method: 'POST',
        headers: this.token ? { Authorization: `Bearer ${this.token}` } : {},
        body: formData,
      })
    } catch {
      throw new CliError('registry unreachable', EXIT.network, {
        registry: this.registry,
        next: 'check network or pass --registry',
      })
    }
    return this.handleJsonResponse(response)
  }

  private async getJson<T>(path: string): Promise<T> {
    let response: Response
    try {
      response = await this.fetchImpl(`${this.registry}/api/v1/cli${path}`, { headers: this.headers() })
    } catch {
      throw new CliError('registry unreachable', EXIT.network, {
        registry: this.registry,
        next: 'check network or pass --registry',
      })
    }
    return this.handleJsonResponse<T>(response)
  }

  private async handleJsonResponse<T>(response: Response): Promise<T> {
    if (response.status === 401) {
      throw new CliError('authentication failed', EXIT.auth, {
        registry: this.registry,
        next: 'run `aihelms login`',
      })
    }
    if (response.status === 403) {
      const detail = await this.readDetail(response)
      throw new CliError(detail || 'access denied — token may lack required scope', EXIT.auth, {
        registry: this.registry,
        next: 'regenerate token with required scopes or run `aihelms login`',
      })
    }
    if (response.status === 404) {
      throw new CliError('resource not found', EXIT.generic, { registry: this.registry })
    }
    if (response.status === 409) {
      const detail = await this.readDetail(response)
      throw new CliError(detail || 'version already exists', EXIT.validation, { registry: this.registry })
    }
    if (response.status === 400) {
      const detail = await this.readDetail(response)
      throw new CliError(detail || 'validation failed', EXIT.validation, { registry: this.registry })
    }
    if (response.status === 502 || response.status === 503) {
      throw new CliError(`registry returned ${response.status}`, EXIT.network, { registry: this.registry })
    }
    if (!response.ok) {
      const detail = await this.readDetail(response)
      throw new CliError(detail || `registry returned ${response.status}`, EXIT.generic, {
        registry: this.registry,
      })
    }

    const body = (await response.json()) as Envelope<T>
    if (body.code !== 200) {
      throw new CliError(body.message || `registry returned code ${body.code}`, EXIT.generic, {
        registry: this.registry,
      })
    }
    return body.data
  }

  private async readDetail(response: Response): Promise<string> {
    try {
      const body = (await response.json()) as { detail?: string; message?: string }
      return body.detail ?? body.message ?? ''
    } catch {
      return ''
    }
  }

  private headers(): HeadersInit {
    return this.token ? { Authorization: `Bearer ${this.token}` } : {}
  }
}
