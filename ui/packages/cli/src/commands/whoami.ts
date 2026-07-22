import { AihelmsClient } from '../clients/aihelms-client'
import { ConfigStore } from '../stores/config-store'
import { CredentialsStore } from '../stores/credentials-store'
import { resolveRegistry, resolveToken } from '../services/registry-service'
import { CliError } from '../shared/errors'
import { EXIT } from '../shared/constants'

export interface WhoamiCommandOptions {
  registry?: string
  token?: string
  json?: boolean
}

export async function whoamiCommand(options: WhoamiCommandOptions): Promise<string> {
  const configStore = new ConfigStore()
  const credentialsStore = new CredentialsStore()
  const registry = resolveRegistry(options, process.env, await configStore.read())
  const token = resolveToken(options, process.env, await credentialsStore.getToken(registry))
  if (!token) {
    throw new CliError('not logged in', EXIT.auth, { registry, next: 'run `aihelms login`' })
  }
  const user = await new AihelmsClient(registry, token).whoami()
  if (options.json) {
    return JSON.stringify({
      ok: true,
      registry,
      ownerId: user.owner_id,
      ownerType: user.owner_type,
      scopes: user.scopes,
    })
  }
  return [
    `Registry: ${registry}`,
    `Owner: ${user.owner_type}#${user.owner_id}`,
    `Scopes: ${user.scopes.join(', ') || '(none)'}`,
  ].join('\n')
}
