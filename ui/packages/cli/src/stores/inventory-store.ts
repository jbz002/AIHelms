import { open, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import { ensureDir, joinPath, pathExists, userStateDir } from '../platform/paths'

export interface InventoryTarget {
  agent: string
  rootDir: string
  installDir: string
  installedAt: string
}

export interface InventoryItem {
  registry: string
  skillId: string
  name: string
  version: string
  targets: InventoryTarget[]
}

export interface Inventory {
  items: InventoryItem[]
}

export class InventoryStore {
  readonly path: string

  constructor(home?: string) {
    this.path = joinPath(userStateDir(home), 'inventory.json')
  }

  async read(): Promise<Inventory> {
    if (!(await pathExists(this.path))) return { items: [] }
    return JSON.parse(await readFile(this.path, 'utf-8')) as Inventory
  }

  async write(inventory: Inventory): Promise<void> {
    await ensureDir(dirname(this.path))
    await writeFile(this.path, JSON.stringify(inventory, null, 2))
  }

  async writeAtomic(inventory: Inventory): Promise<void> {
    await ensureDir(dirname(this.path))
    const payload = JSON.stringify(inventory, null, 2)
    JSON.parse(payload)

    const lockPath = `${this.path}.lock`
    const tmpPath = `${this.path}.${process.pid}.${Date.now()}.tmp`

    let lockHandle: Awaited<ReturnType<typeof open>> | null = null
    try {
      lockHandle = await this.acquireLock(lockPath)
      await writeFile(tmpPath, payload)
      JSON.parse(await readFile(tmpPath, 'utf-8'))
      await rename(tmpPath, this.path)
    } finally {
      await rm(tmpPath, { force: true }).catch(() => {})
      if (lockHandle) {
        await lockHandle.close().catch(() => {})
        await rm(lockPath, { force: true }).catch(() => {})
      }
    }
  }

  private async acquireLock(
    lockPath: string,
    maxRetries = 10,
    retryDelayMs = 100,
  ): Promise<Awaited<ReturnType<typeof open>>> {
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const lockHandle = await open(lockPath, 'wx')
        const lockData = JSON.stringify({ pid: process.pid, timestamp: Date.now() })
        await writeFile(lockPath, lockData)
        return lockHandle
      } catch (err) {
        if (err instanceof Error && 'code' in err && err.code !== 'EEXIST') throw err

        try {
          const lockContent = await readFile(lockPath, 'utf-8')
          const lockData = JSON.parse(lockContent) as { pid: number; timestamp: number }
          const ageMs = Date.now() - lockData.timestamp

          if (ageMs > 30000) {
            try {
              process.kill(lockData.pid, 0)
            } catch {
              await rm(lockPath, { force: true }).catch(() => {})
              continue
            }
          }
        } catch {
          continue
        }

        if (attempt < maxRetries - 1) {
          await new Promise(resolve => setTimeout(resolve, retryDelayMs * Math.pow(2, attempt)))
        }
      }
    }
    throw new Error(`Failed to acquire lock after ${maxRetries} attempts`)
  }

  async upsertTarget(
    registry: string,
    skillId: string,
    name: string,
    version: string,
    target: InventoryTarget,
  ): Promise<void> {
    const inventory = await this.read()
    let item = inventory.items.find(i => i.registry === registry && i.skillId === skillId)
    if (!item) {
      item = { registry, skillId, name, version, targets: [] }
      inventory.items.push(item)
    }
    item.name = name
    item.version = version
    const existingIdx = item.targets.findIndex(t => t.installDir === target.installDir)
    if (existingIdx >= 0) {
      item.targets[existingIdx] = target
    } else {
      item.targets.push(target)
    }
    await this.writeAtomic(inventory)
  }

  async removeTarget(registry: string, skillId: string, installDir: string): Promise<boolean> {
    const inventory = await this.read()
    const item = inventory.items.find(i => i.registry === registry && i.skillId === skillId)
    if (!item) return false
    const idx = item.targets.findIndex(t => t.installDir === installDir)
    if (idx < 0) return false
    item.targets.splice(idx, 1)
    if (item.targets.length === 0) {
      inventory.items = inventory.items.filter(i => i !== item)
    }
    await this.writeAtomic(inventory)
    return true
  }

  async removeTargetsByInstallDir(installDir: string): Promise<number> {
    const inventory = await this.read()
    let removed = 0
    for (const item of inventory.items) {
      const before = item.targets.length
      item.targets = item.targets.filter(t => t.installDir !== installDir)
      removed += before - item.targets.length
    }
    if (removed > 0) {
      inventory.items = inventory.items.filter(item => item.targets.length > 0)
      await this.writeAtomic(inventory)
    }
    return removed
  }
}
