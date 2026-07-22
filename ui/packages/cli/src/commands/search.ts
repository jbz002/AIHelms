import { AihelmsClient } from '../clients/aihelms-client'
import { ConfigStore } from '../stores/config-store'
import { CredentialsStore } from '../stores/credentials-store'
import { resolveRegistry, resolveToken } from '../services/registry-service'

export interface SearchCommandOptions {
  registry?: string
  token?: string
  category?: string
  label?: string
  sort?: string
  limit?: number
  json?: boolean
}

export async function searchCommand(query: string, options: SearchCommandOptions): Promise<string> {
  const configStore = new ConfigStore()
  const credentialsStore = new CredentialsStore()
  const registry = resolveRegistry(options, process.env, await configStore.read())
  const token = resolveToken(options, process.env, await credentialsStore.getToken(registry))
  const client = new AihelmsClient(registry, token)
  const result = await client.search(query, {
    category: options.category,
    label: options.label,
    sort: options.sort,
    limit: options.limit ?? 20,
  })
  if (options.json) {
    return JSON.stringify({ ok: true, items: result.items, total: result.total })
  }
  if (result.items.length === 0) return 'No skills found.'
  return result.items
    .map(item => {
      const labels = item.labels && item.labels.length > 0 ? `  [${item.labels.join(', ')}]` : ''
      return `${item.skill_id}  ${item.name}  ${item.version || '-'}${labels}\n    ${item.description ?? ''}`
    })
    .join('\n')
}
