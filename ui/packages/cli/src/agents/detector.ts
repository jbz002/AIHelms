import type { AgentProfile } from './types'
import { claudeCodeProfile } from './profiles/claude-code'
import { codexProfile } from './profiles/codex'
import { cursorProfile } from './profiles/cursor'
import { githubCopilotProfile } from './profiles/github-copilot'
import { geminiCliProfile } from './profiles/gemini-cli'
import { openhandsProfile } from './profiles/openhands'
import { windsurfProfile } from './profiles/windsurf'
import { genericFallbackProfile } from './profiles/generic-fallback'

export {
  claudeCodeProfile,
  codexProfile,
  cursorProfile,
  githubCopilotProfile,
  geminiCliProfile,
  openhandsProfile,
  windsurfProfile,
  genericFallbackProfile,
}

/** 首版支持的主流 agent（roadmap §五），按检测优先级排列。 */
export const allProfiles: AgentProfile[] = [
  claudeCodeProfile,
  codexProfile,
  cursorProfile,
  githubCopilotProfile,
  geminiCliProfile,
  windsurfProfile,
  openhandsProfile,
]

export const profileMap = new Map(allProfiles.map(p => [p.id, p]))
