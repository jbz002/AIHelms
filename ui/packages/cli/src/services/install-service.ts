import { mkdir, mkdtemp, rename, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { AihelmsClient } from '../clients/aihelms-client'
import { InventoryStore } from '../stores/inventory-store'
import { CliError } from '../shared/errors'
import { EXIT } from '../shared/constants'
import { extractZip } from '../platform/archive'
import { readBoundedResponseBody } from '../platform/download'
import { pathExists } from '../platform/paths'
import { isUuid } from '../shared/coordinate'
import type { AgentCandidate } from '../agents/types'

export interface InstallOptions {
  registry: string
  token?: string
  /** UUID 或 skill name。 */
  arg: string
  version?: string
  targets: AgentCandidate[]
  force: boolean
  home?: string
}

interface ResolvedSkill {
  skillId: string
  name: string
  activeVersion: string
}

/** skill name 含路径分隔符/特殊字符时 sanitize 为安全目录名。 */
function sanitizeSkillDirName(name: string): string {
  const cleaned = name.replace(/[/\\<>:"|?*\s]+/g, '-').replace(/^-+|-+$/g, '')
  return cleaned || 'skill'
}

async function resolveSkillForInstall(client: AihelmsClient, arg: string): Promise<ResolvedSkill> {
  if (isUuid(arg)) {
    const detail = await client.getSkill(arg)
    const versions = await client.listVersions(arg)
    const active = versions.find(v => v.is_active) ?? versions[0]
    return { skillId: arg, name: detail.name, activeVersion: active?.version ?? '' }
  }
  const result = await client.search(arg, { limit: 50 })
  const exact = result.items.find(i => i.name === arg)
  const fuzzy = result.items.find(i => i.name.toLowerCase().includes(arg.toLowerCase()))
  const match = exact ?? fuzzy
  if (!match) {
    throw new CliError(`skill not found: ${arg}`, EXIT.generic, {
      next: 'run `aihelms search <query>` to list published skills',
    })
  }
  return { skillId: match.skill_id, name: match.name, activeVersion: match.version ?? '' }
}

export async function installSkill(
  options: InstallOptions,
): Promise<{ installed: Array<{ agent: string; dir: string }> }> {
  const client = new AihelmsClient(options.registry, options.token)
  const resolved = await resolveSkillForInstall(client, options.arg)
  const effectiveVersion = options.version ?? resolved.activeVersion

  const response = await client.download(resolved.skillId, options.version)
  const buffer = await readBoundedResponseBody(response)

  const skillDirName = sanitizeSkillDirName(resolved.name)
  const installed: Array<{ agent: string; dir: string }> = []
  const store = new InventoryStore(options.home)

  for (const target of options.targets) {
    const skillDir = join(target.rootDir, skillDirName)

    if ((await pathExists(skillDir)) && !options.force) {
      throw new CliError(`skill already installed at ${skillDir}`, EXIT.filesystem, {
        path: skillDir,
        next: 'pass --force to overwrite',
      })
    }

    await mkdir(target.rootDir, { recursive: true })
    const tempDir = await mkdtemp(join(target.rootDir, `.${skillDirName}.install-`))
    let movedIntoPlace = false

    try {
      await extractZip(buffer, tempDir)

      const installedAt = new Date().toISOString()
      const metaDir = join(tempDir, '.aihelms')
      await mkdir(metaDir, { recursive: true })
      await writeFile(
        join(metaDir, 'metadata.json'),
        JSON.stringify(
          {
            registry: options.registry,
            skillId: resolved.skillId,
            name: resolved.name,
            version: effectiveVersion,
            agent: target.agent,
            installedAt,
          },
          null,
          2,
        ),
      )

      if ((await pathExists(skillDir)) && !options.force) {
        throw new CliError(`skill already installed at ${skillDir}`, EXIT.filesystem, {
          path: skillDir,
          next: 'pass --force to overwrite',
        })
      }

      if ((await pathExists(skillDir)) && options.force) {
        await store.removeTargetsByInstallDir(skillDir)
        await rm(skillDir, { recursive: true, force: true })
      }

      try {
        await rename(tempDir, skillDir)
      } catch (error) {
        if (!options.force && (await pathExists(skillDir))) {
          throw new CliError(`skill already installed at ${skillDir}`, EXIT.filesystem, {
            path: skillDir,
            next: 'pass --force to overwrite',
          })
        }
        throw error
      }
      movedIntoPlace = true

      await store.upsertTarget(options.registry, resolved.skillId, resolved.name, effectiveVersion, {
        agent: target.agent,
        rootDir: target.rootDir,
        installDir: skillDir,
        installedAt,
      })
    } finally {
      if (!movedIntoPlace) {
        await rm(tempDir, { recursive: true, force: true }).catch(() => {})
      }
    }

    installed.push({ agent: target.agent, dir: skillDir })
  }

  return { installed }
}
