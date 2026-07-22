import { ConfigStore } from '../stores/config-store'
import { CredentialsStore } from '../stores/credentials-store'
import { resolveRegistry } from '../services/registry-service'
import { removeLocalSkill } from '../services/remove-service'
import { CliError } from '../shared/errors'
import { EXIT } from '../shared/constants'

export interface RemoveCommandOptions {
  agent?: string[]
  all?: boolean
  registry?: string
  token?: string
  json?: boolean
}

export async function removeCommand(skillArg: string, options: RemoveCommandOptions): Promise<string> {
  if (options.all && options.agent?.length) {
    throw new CliError('--all cannot be used with --agent', EXIT.usage)
  }

  const configStore = new ConfigStore()
  const credentialsStore = new CredentialsStore()
  const registry = resolveRegistry(options, process.env, await configStore.read())

  const result = await removeLocalSkill({
    registry,
    arg: skillArg,
    agents: options.agent,
    all: options.all,
  })

  if (options.json) {
    return JSON.stringify({ ok: true, scope: 'local', removed: result.removed })
  }
  return result.removed
    .map(r =>
      r.existed
        ? `Removed ${skillArg} from ${r.dir} (${r.agent})`
        : `Cleaned stale record for ${skillArg} at ${r.dir} (${r.agent}, directory already missing)`,
    )
    .join('\n')
}
