import { ConfigStore } from '../stores/config-store'
import { CredentialsStore } from '../stores/credentials-store'
import { resolveRegistry, resolveToken } from '../services/registry-service'
import { installSkill } from '../services/install-service'
import { resolveInstallTargets } from '../agents/resolver'
import { CliError } from '../shared/errors'
import { EXIT } from '../shared/constants'

export interface InstallCommandOptions {
  version?: string
  agent?: string[]
  dir?: string
  scope?: string
  force?: boolean
  registry?: string
  token?: string
  json?: boolean
}

export function computeStrictIsTTY(env: {
  stdinIsTTY: boolean
  stdoutIsTTY: boolean
  json: boolean
}): boolean {
  return env.stdinIsTTY && env.stdoutIsTTY && !env.json
}

async function defaultPromptScope(): Promise<'user' | 'project'> {
  const prompts = (await import('prompts')).default
  const { scope } = await prompts({
    type: 'select',
    name: 'scope',
    message: 'Install for user or project?',
    choices: [
      { title: 'User (install to user-level agent directory)', value: 'user' },
      { title: 'Project (install to project-level agent directory)', value: 'project' },
    ],
  })
  if (!scope) {
    throw new CliError('installation cancelled', EXIT.usage)
  }
  return scope as 'user' | 'project'
}

async function resolveEffectiveScope(
  options: InstallCommandOptions,
  isTTY: boolean,
): Promise<'user' | 'project' | undefined> {
  if (options.scope !== undefined && options.scope !== 'user' && options.scope !== 'project') {
    throw new CliError('--scope must be "user" or "project"', EXIT.usage)
  }
  const scope = options.scope as 'user' | 'project' | undefined
  const agentList = options.agent ?? []

  if (options.dir && scope !== undefined) {
    throw new CliError('--dir cannot be used with --scope', EXIT.usage)
  }
  if (options.dir && agentList.length > 0) {
    throw new CliError('--dir cannot be used with --agent', EXIT.usage)
  }

  if (scope !== undefined) return scope
  if (options.dir || agentList.length > 0) return undefined
  if (isTTY) return await defaultPromptScope()
  return undefined
}

export async function installCommand(skillArg: string, options: InstallCommandOptions): Promise<string> {
  const isTTY = computeStrictIsTTY({
    stdinIsTTY: process.stdin.isTTY === true,
    stdoutIsTTY: process.stdout.isTTY === true,
    json: Boolean(options.json),
  })
  const effectiveScope = await resolveEffectiveScope(options, isTTY)

  const configStore = new ConfigStore()
  const credentialsStore = new CredentialsStore()
  const registry = resolveRegistry(options, process.env, await configStore.read())
  const token = resolveToken(options, process.env, await credentialsStore.getToken(registry))

  const targets = await resolveInstallTargets({
    cwd: process.cwd(),
    scope: effectiveScope,
    dir: options.dir,
    agents: options.agent ?? [],
    json: Boolean(options.json),
    interactive: isTTY,
  })

  const result = await installSkill({
    registry,
    token,
    arg: skillArg,
    version: options.version,
    targets,
    force: Boolean(options.force),
  })

  if (options.json) {
    return JSON.stringify({ ok: true, installed: result.installed })
  }
  return result.installed
    .map(i => `Installed ${skillArg} -> ${i.dir} (${i.agent})`)
    .join('\n')
}
