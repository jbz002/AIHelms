import { isUuid } from '../shared/coordinate'
import { EXIT } from '../shared/constants'
import { CliError } from '../shared/errors'
import { createZip, isZipFile } from '../platform/archive'
import { AihelmsClient } from '../clients/aihelms-client'
import type { SkillVersion } from '../clients/aihelms-client'

export interface PublishOptions {
  registry: string
  token?: string
  /** 目标 Skill 的 UUID。 */
  skillId: string
  /** 本地 zip 文件或目录路径。 */
  path: string
  version: string
  versionLabel?: string
  changeLog?: string
}

export interface PublishResult {
  version: SkillVersion
}

async function readPathStat(path: string): Promise<{ isFile: boolean; isDirectory: boolean }> {
  const { stat } = await import('node:fs/promises')
  try {
    const st = await stat(path)
    return { isFile: st.isFile(), isDirectory: st.isDirectory() }
  } catch {
    throw new CliError(`path not found: ${path}`, EXIT.filesystem, { path })
  }
}

async function buildArchive(
  path: string,
  isFile: boolean,
  isDirectory: boolean,
): Promise<{ blob: Blob; name: string }> {
  const { basename } = await import('node:path')
  const { readFile } = await import('node:fs/promises')
  if (isFile) {
    if (!(await isZipFile(path))) {
      throw new CliError(`file must be a zip archive: ${path}`, EXIT.filesystem, { path })
    }
    const buffer = await readFile(path)
    return { blob: new Blob([buffer], { type: 'application/zip' }), name: basename(path) }
  }
  if (isDirectory) {
    const blob = await createZip(path)
    return { blob, name: `${basename(path)}.zip` }
  }
  throw new CliError(`path must be a file or directory: ${path}`, EXIT.filesystem, { path })
}

export async function publishSkill(options: PublishOptions): Promise<PublishResult> {
  if (!isUuid(options.skillId)) {
    throw new CliError(
      `publish 需要目标 Skill 的 UUID，收到: ${options.skillId}`,
      EXIT.usage,
      { next: 'run `aihelms search <name>` to find the skill_id (UUID)' },
    )
  }
  if (!options.token) {
    throw new CliError('authentication required for publish', EXIT.auth, { next: 'run `aihelms login`' })
  }

  const { isFile, isDirectory } = await readPathStat(options.path)
  const { blob, name } = await buildArchive(options.path, isFile, isDirectory)

  const client = new AihelmsClient(options.registry, options.token)
  const result = await client.publishVersion(options.skillId, blob, {
    version: options.version,
    version_label: options.versionLabel,
    change_log: options.changeLog,
  }, name)

  return { version: result.version }
}
