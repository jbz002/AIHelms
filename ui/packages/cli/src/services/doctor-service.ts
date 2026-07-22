import { lstat, readdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { CliError } from '../shared/errors'
import { EXIT } from '../shared/constants'
import type { Inventory, InventoryItem, InventoryTarget } from '../stores/inventory-store'
import { InventoryStore } from '../stores/inventory-store'

interface MetadataJson {
  registry: string
  skillId: string
  name: string
  version: string
  agent: string
  installedAt: string
}

interface DoctorResult {
  inventoryPath: string
  backupPath: string | null
  itemsScanned: number
  targetsScanned: number
  itemsPreserved: number
  targetsPreserved: number
  skipped: Array<{ path: string; reason: string }>
  conflicts: Array<{ key: string; versions: string[] }>
}

export async function runDoctor(cwd: string, home?: string): Promise<DoctorResult> {
  const store = new InventoryStore(home)
  const skipped: DoctorResult['skipped'] = []
  const conflicts: DoctorResult['conflicts'] = []

  const entries = await scanMetadata(cwd, skipped)

  // 按 registry + skillId 分组
  const groups = new Map<string, { metadata: MetadataJson; installDir: string }[]>()
  for (const entry of entries) {
    const key = `${entry.metadata.registry}|${entry.metadata.skillId}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(entry)
  }

  const scannedItems: InventoryItem[] = []
  for (const [key, group] of groups) {
    const versions = new Set(group.map(e => e.metadata.version))
    if (versions.size > 1) {
      conflicts.push({ key, versions: [...versions] })
      continue
    }
    const first = group[0]!
    const targets: InventoryTarget[] = group.map(e => ({
      agent: e.metadata.agent,
      rootDir: join(e.installDir, '..'),
      installDir: e.installDir,
      installedAt: e.metadata.installedAt,
    }))
    scannedItems.push({
      registry: first.metadata.registry,
      skillId: first.metadata.skillId,
      name: first.metadata.name,
      version: first.metadata.version,
      targets,
    })
  }

  let oldInventory: Inventory
  try {
    oldInventory = await store.read()
  } catch {
    oldInventory = { items: [] }
  }

  const scannedInstallDirs = new Set<string>()
  for (const item of scannedItems) {
    for (const target of item.targets) {
      scannedInstallDirs.add(target.installDir)
    }
  }

  // 保留扫描范围外的旧记录（不同项目可共存）
  const preservedItems: InventoryItem[] = []
  for (const oldItem of oldInventory.items) {
    const preservedTargets = oldItem.targets.filter(t => !scannedInstallDirs.has(t.installDir))
    if (preservedTargets.length > 0) {
      preservedItems.push({ ...oldItem, targets: preservedTargets })
    }
  }

  const items = [...scannedItems, ...preservedItems]

  let backupPath: string | null = null
  try {
    const oldContent = await readFile(store.path, 'utf-8')
    backupPath = `${store.path}.bak`
    await writeFile(backupPath, oldContent)
  } catch {
    // 无旧 inventory 可备份
  }

  await store.writeAtomic({ items })

  return {
    inventoryPath: store.path,
    backupPath,
    itemsScanned: scannedItems.length,
    targetsScanned: scannedItems.reduce((sum, item) => sum + item.targets.length, 0),
    itemsPreserved: preservedItems.length,
    targetsPreserved: preservedItems.reduce((sum, item) => sum + item.targets.length, 0),
    skipped,
    conflicts,
  }
}

async function scanMetadata(
  cwd: string,
  skipped: DoctorResult['skipped'],
): Promise<Array<{ metadata: MetadataJson; installDir: string }>> {
  const results: Array<{ metadata: MetadataJson; installDir: string }> = []

  let topEntries: string[]
  try {
    topEntries = await readdir(cwd)
  } catch {
    throw new CliError('cannot read project directory', EXIT.filesystem, { path: cwd })
  }

  for (const dirName of topEntries) {
    if (!dirName.startsWith('.')) continue
    const agentDir = join(cwd, dirName)
    try {
      const st = await lstat(agentDir)
      if (st.isSymbolicLink() || !st.isDirectory()) {
        skipped.push({ path: agentDir, reason: 'not a regular directory' })
        continue
      }
    } catch {
      skipped.push({ path: agentDir, reason: 'cannot stat' })
      continue
    }
    const skillsDir = join(agentDir, 'skills')
    let nameDirs: string[]
    try {
      nameDirs = await readdir(skillsDir)
    } catch {
      continue
    }

    for (const name of nameDirs) {
      const namePath = join(skillsDir, name)
      try {
        const st = await lstat(namePath)
        if (st.isSymbolicLink() || !st.isDirectory()) {
          skipped.push({ path: namePath, reason: 'not a regular directory' })
          continue
        }
      } catch {
        skipped.push({ path: namePath, reason: 'cannot stat' })
        continue
      }
      const aihelmsDir = join(namePath, '.aihelms')
      try {
        const aihelmsSt = await lstat(aihelmsDir)
        if (aihelmsSt.isSymbolicLink() || !aihelmsSt.isDirectory()) {
          skipped.push({ path: namePath, reason: '.aihelms is not a regular directory' })
          continue
        }
      } catch {
        skipped.push({ path: namePath, reason: 'no .aihelms directory' })
        continue
      }
      const metadataPath = join(aihelmsDir, 'metadata.json')
      try {
        const content = await readFile(metadataPath, 'utf-8')
        const metadata = JSON.parse(content) as MetadataJson
        if (
          !metadata.registry ||
          !metadata.skillId ||
          !metadata.name ||
          !metadata.version ||
          !metadata.agent ||
          !metadata.installedAt
        ) {
          skipped.push({ path: namePath, reason: 'incomplete metadata' })
          continue
        }
        results.push({ metadata, installDir: namePath })
      } catch {
        skipped.push({ path: namePath, reason: 'no .aihelms/metadata.json' })
      }
    }
  }

  return results
}
