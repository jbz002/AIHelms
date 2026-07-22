import { ConfigStore } from '../stores/config-store'
import { CredentialsStore } from '../stores/credentials-store'
import { resolveRegistry, resolveToken } from '../services/registry-service'
import { publishSkill } from '../services/publish-service'
import { CliError } from '../shared/errors'
import { EXIT } from '../shared/constants'

export interface PublishCommandOptions {
  version?: string
  label?: string
  changeLog?: string
  registry?: string
  token?: string
  json?: boolean
}

export async function publishCommand(
  skillId: string,
  path: string,
  options: PublishCommandOptions,
): Promise<string> {
  if (!options.version) {
    throw new CliError('--version is required for publish', EXIT.usage, {
      next: 'pass --version <semver>, e.g. aihelms publish <uuid> ./skill --version 1.2.0',
    })
  }

  const configStore = new ConfigStore()
  const credentialsStore = new CredentialsStore()
  const registry = resolveRegistry(options, process.env, await configStore.read())
  const token = resolveToken(options, process.env, await credentialsStore.getToken(registry))

  const result = await publishSkill({
    registry,
    token,
    skillId,
    path,
    version: options.version,
    versionLabel: options.label,
    changeLog: options.changeLog,
  })

  const version = result.version
  if (options.json) {
    return JSON.stringify({
      ok: true,
      skillId,
      version: version.version,
      lifecycleStatus: version.lifecycle_status,
      reviewTaskId: (result.reviewTask as { id?: number }).id ?? null,
    })
  }
  return [
    `Submitted version ${version.version} for review.`,
    `Skill: ${skillId}`,
    `Status: ${version.lifecycle_status}`,
  ].join('\n')
}
