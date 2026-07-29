import { printResult } from '../shared/output'

export const commands = {
  help: {
    summary: 'Show available commands',
    usage: 'aihelms help [command] [--json]',
    examples: ['aihelms help', 'aihelms help install', 'aihelms help --json'],
  },
  version: {
    summary: 'Show installed CLI version',
    usage: 'aihelms version [--json]',
    examples: ['aihelms version', 'aihelms version --json'],
  },
  login: {
    summary: 'Save registry and CLI token',
    usage: 'aihelms login --registry <url> --token <sk_cli_...> [--json]',
    examples: ['aihelms login --registry http://localhost:8000 --token sk_cli_xxx'],
  },
  logout: {
    summary: 'Remove local token',
    usage: 'aihelms logout [--registry <url>] [--json]',
    examples: ['aihelms logout'],
  },
  whoami: {
    summary: 'Verify current token and scopes',
    usage: 'aihelms whoami [--token <token>] [--registry <url>] [--json]',
    examples: ['aihelms whoami', 'aihelms whoami --json'],
  },
  search: {
    summary: 'Search published skills',
    usage:
      'aihelms search [query] [--category <c>] [--sort newest|install_count|name] [--limit <n>] [--json]',
    examples: ['aihelms search pdf', 'aihelms search --category data'],
  },
  install: {
    summary: 'Install a skill locally (UUID or name)',
    usage:
      'aihelms install <skill-id|name> [--scope <user|project>] [--version <v>] [--agent <profile>] [--dir <path>] [--force] [--json]',
    examples: [
      'aihelms install pdf-parser',
      'aihelms install 550e8400-... --scope user',
      'aihelms install pdf-parser --scope project --agent codex',
    ],
  },
  list: {
    summary: 'List local installs',
    usage: 'aihelms list [--agent <profile>] [--dir <path>] [--registry <url>] [--json]',
    examples: ['aihelms list', 'aihelms list --agent codex'],
  },
  remove: {
    summary: 'Remove a locally installed skill',
    usage: 'aihelms remove <skill-id|name> [--agent <profile>] [--all] [--json]',
    examples: ['aihelms remove pdf-parser', 'aihelms remove pdf-parser --all'],
  },
  doctor: {
    summary: 'Scan project skills and rebuild local inventory (detect version conflicts)',
    usage: 'aihelms doctor [--json]',
    examples: ['aihelms doctor', 'aihelms doctor --json'],
  },
  publish: {
    summary: 'Publish a new skill version for review (UUID + local zip/dir)',
    usage:
      'aihelms publish <skill-id> <path> --version <v> [--label <l>] [--change-log <text>] [--json]',
    examples: [
      'aihelms publish 550e8400-... ./my-skill --version 1.2.0',
      'aihelms publish 550e8400-... ./skill.zip --version 1.2.0 --change-log "fix"',
    ],
  },
} as const

export function formatCommandList(): string {
  return Object.entries(commands)
    .map(([name, detail]) => `${name.padEnd(10)} ${detail.summary}`)
    .join('\n')
}

export async function helpCommand(args: string[]): Promise<string> {
  const json = args.includes('--json')
  const topic = args.find(arg => !arg.startsWith('--'))
  if (json) {
    if (topic) {
      const detail = commands[topic as keyof typeof commands]
      return printResult(detail ? { ok: true, command: topic, ...detail } : { ok: false, message: `unknown command ${topic}` }, true)
    }
    return printResult(
      {
        ok: true,
        commands: Object.entries(commands).map(([name, detail]) => ({ name, description: detail.summary })),
      },
      true,
    )
  }
  if (topic) {
    const detail = commands[topic as keyof typeof commands]
    if (!detail) return `unknown command: ${topic}`
    return [
      `${topic} - ${detail.summary}`,
      `Usage: ${detail.usage}`,
      'Examples:',
      ...detail.examples.map(example => `  ${example}`),
    ].join('\n')
  }
  return formatCommandList()
}
