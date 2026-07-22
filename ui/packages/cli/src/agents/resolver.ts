import { homedir } from 'node:os'
import { EXIT } from '../shared/constants'
import { CliError } from '../shared/errors'
import { ensureDir, pathExists } from '../platform/paths'
import type { AgentCandidate } from './types'
import { allProfiles, profileMap } from './detector'

export interface ResolveInstallTargetOptions {
  cwd: string
  home?: string
  dir?: string
  agents?: string[]
  scope?: 'user' | 'project'
  json: boolean
  interactive: boolean
  detected?: AgentCandidate[]
}

/**
 * 4 级目录优先级（roadmap §4.7，兼容 OpenSkills/Claude Code）：
 * ./.agents/skills → ~/.agents/skills → ./.claude/skills → ~/.claude/skills
 * 仅在未检测到 agent 且无显式指定时作为 fallback，选第一个可写目录。
 */
const FALLBACK_LADDER = (cwd: string, home: string): Array<{ agent: string; rootDir: string; scope: 'project' | 'user' }> => [
  { agent: 'generic', rootDir: `${cwd}/.agents/skills`, scope: 'project' },
  { agent: 'generic', rootDir: `${home}/.agents/skills`, scope: 'user' },
  { agent: 'claude-code', rootDir: `${cwd}/.claude/skills`, scope: 'project' },
  { agent: 'claude-code', rootDir: `${home}/.claude/skills`, scope: 'user' },
]

export async function resolveInstallTargets(options: ResolveInstallTargetOptions): Promise<AgentCandidate[]> {
  const agentList = options.agents ?? []

  if (options.dir && agentList.length > 0) {
    throw new CliError('--dir cannot be used with --agent', EXIT.usage)
  }
  if (options.dir && options.scope !== undefined) {
    throw new CliError('--dir cannot be used with --scope', EXIT.usage)
  }
  if (options.dir) {
    return [{ agent: 'custom', rootDir: options.dir, scope: 'user', source: 'explicit' }]
  }

  if (options.scope !== undefined) {
    return resolveScopedTargets(options, agentList)
  }

  if (agentList.length > 0) {
    const resolved = await resolveExplicitAgents(agentList, options.cwd, options.home ?? homedir())
    return dedupeByRoot(resolved)
  }

  const detected = options.detected ?? (await detectAll(options.cwd, options.home ?? ''))
  if (detected.length === 1) return detected
  if (detected.length > 1 && options.interactive && !options.json) {
    return selectTargetsInteractively(detected)
  }
  if (detected.length > 1 && (!options.interactive || options.json)) {
    throw new CliError('multiple install targets detected', EXIT.usage, {
      next: 'pass --agent or --dir',
      candidates: detected,
    })
  }

  return resolveLadderFallback(options.cwd, options.home ?? homedir())
}

async function resolveLadderFallback(cwd: string, home: string): Promise<AgentCandidate[]> {
  for (const rung of FALLBACK_LADDER(cwd, home)) {
    try {
      await ensureDir(rung.rootDir)
      return [{ agent: rung.agent, rootDir: rung.rootDir, scope: rung.scope, source: 'fallback' }]
    } catch {
      // 当前阶梯不可写，尝试下一级
    }
  }
  throw new CliError('no writable install directory found', EXIT.filesystem, {
    next: 'pass --dir <path> to specify an explicit install directory',
  })
}

async function resolveScopedTargets(
  options: ResolveInstallTargetOptions,
  agentList: string[],
): Promise<AgentCandidate[]> {
  const scope = options.scope!
  const scopedHome = options.home ?? homedir()

  let candidates: AgentCandidate[]
  if (agentList.length > 0) {
    candidates = await resolveExplicitAgents(agentList, options.cwd, scopedHome, scope)
  } else if (options.detected !== undefined) {
    candidates = options.detected.filter(c => c.scope === scope)
  } else {
    candidates = await generateScopedCandidates(scope, options.cwd, scopedHome)
  }
  candidates = dedupeByRoot(candidates)

  if (candidates.length === 0) {
    const rungs = FALLBACK_LADDER(options.cwd, scopedHome).filter(r => r.scope === scope)
    for (const rung of rungs) {
      try {
        await ensureDir(rung.rootDir)
        return [{ agent: rung.agent, rootDir: rung.rootDir, scope, source: 'fallback' }]
      } catch {
        // continue
      }
    }
    throw new CliError('no writable install directory found', EXIT.filesystem, {
      next: 'pass --dir <path> to specify an explicit install directory',
    })
  }
  if (candidates.length === 1) return candidates
  if (options.interactive && !options.json) {
    return selectTargetsInteractively(candidates)
  }
  throw new CliError('multiple install targets detected', EXIT.usage, {
    next: 'pass --agent or --dir',
    candidates,
  })
}

async function generateScopedCandidates(
  scope: 'user' | 'project',
  cwd: string,
  home: string,
): Promise<AgentCandidate[]> {
  const results: AgentCandidate[] = []
  for (const profile of allProfiles) {
    const roots = scope === 'user' ? profile.userRoots(home) : profile.projectRoots(cwd)
    for (const root of roots) {
      if (await pathExists(root)) {
        results.push({ agent: profile.id, rootDir: root, scope, source: 'detected' })
      }
    }
  }
  return results
}

async function detectAll(cwd: string, home: string): Promise<AgentCandidate[]> {
  const results: AgentCandidate[] = []
  for (const profile of allProfiles) {
    const candidates = await profile.detectInstalled(cwd, home)
    results.push(...candidates)
  }
  return dedupeByRoot(results)
}

async function resolveExplicitAgents(
  agents: string[],
  cwd: string,
  home: string,
  scope?: 'user' | 'project',
): Promise<AgentCandidate[]> {
  const results: AgentCandidate[] = []
  for (const agentId of agents) {
    const profile = profileMap.get(agentId)
    if (!profile) {
      throw new CliError(`unknown agent: ${agentId}`, EXIT.usage, {
        next: 'use a supported agent profile or pass --dir',
      })
    }
    let roots: string[]
    if (scope === 'user') {
      roots = profile.userRoots(home)
    } else if (scope === 'project') {
      roots = profile.projectRoots(cwd)
    } else {
      const userRoots = home ? profile.userRoots(home) : []
      roots = userRoots.length > 0 ? userRoots : profile.projectRoots(cwd)
    }
    const userRootSet = new Set(home ? profile.userRoots(home) : [])
    for (const root of roots) {
      const candidateScope: AgentCandidate['scope'] =
        scope !== undefined ? scope : userRootSet.has(root) ? 'user' : 'project'
      results.push({
        agent: agentId,
        rootDir: root,
        scope: candidateScope,
        source: 'explicit',
      })
    }
  }
  return results
}

function dedupeByRoot(candidates: AgentCandidate[]): AgentCandidate[] {
  const seen = new Set<string>()
  return candidates.filter(c => {
    if (seen.has(c.rootDir)) return false
    seen.add(c.rootDir)
    return true
  })
}

async function selectTargetsInteractively(candidates: AgentCandidate[]): Promise<AgentCandidate[]> {
  const prompts = (await import('prompts')).default
  let highlightedIndex = 0
  const { selected } = await prompts({
    type: 'multiselect',
    name: 'selected',
    message: 'Select install targets',
    choices: candidates.map(c => ({
      title: `${c.agent} (${c.rootDir})`,
      value: c,
    })),
    onRender: function (this: { cursor?: number }) {
      highlightedIndex = this.cursor ?? highlightedIndex
    },
    format: (selectedTargets: AgentCandidate[]) =>
      selectedTargets.length > 0 ? selectedTargets : [candidates[highlightedIndex] ?? candidates[0]],
  })
  if (!selected || selected.length === 0) {
    throw new CliError('installation cancelled', EXIT.usage)
  }
  return selected
}
