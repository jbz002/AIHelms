#!/usr/bin/env node
import { cac } from 'cac'
import { doctorCommand } from './commands/doctor'
import { commands, formatCommandList, helpCommand } from './commands/help'
import { installCommand, type InstallCommandOptions } from './commands/install'
import { listCommand, type ListCommandOptions } from './commands/list'
import { loginCommand } from './commands/login'
import { logoutCommand } from './commands/logout'
import { publishCommand, type PublishCommandOptions } from './commands/publish'
import { removeCommand, type RemoveCommandOptions } from './commands/remove'
import { searchCommand } from './commands/search'
import { versionCommand } from './commands/version'
import { whoamiCommand } from './commands/whoami'
import { CliError } from './shared/errors'
import { renderError } from './shared/output'

const cli = cac('aihelms')

function toArray(val: string | string[] | undefined): string[] | undefined {
  if (val === undefined) return undefined
  return Array.isArray(val) ? val : [val]
}

async function runCommand(action: () => Promise<string>, json = false): Promise<void> {
  try {
    const output = await action()
    if (output) {
      process.stdout.write(`${output}\n`)
    }
  } catch (error) {
    const exitCode = error instanceof CliError ? error.exitCode : 1
    process.stderr.write(`${renderError(error, json)}\n`)
    process.exit(exitCode)
  }
}

const KNOWN_COMMANDS = Object.keys(commands)

function levenshteinDistance(left: string, right: string): number {
  const rows = left.length + 1
  const cols = right.length + 1
  const matrix = Array.from({ length: rows }, () => Array<number>(cols).fill(0))

  for (let row = 0; row < rows; row += 1) matrix[row]![0] = row
  for (let col = 0; col < cols; col += 1) matrix[0]![col] = col

  for (let row = 1; row < rows; row += 1) {
    for (let col = 1; col < cols; col += 1) {
      const cost = left[row - 1] === right[col - 1] ? 0 : 1
      matrix[row]![col] = Math.min(
        matrix[row - 1]![col]! + 1,
        matrix[row]![col - 1]! + 1,
        matrix[row - 1]![col - 1]! + cost,
      )
    }
  }

  return matrix[left.length]![right.length]!
}

function findCommandSuggestions(input: string): string[] {
  return KNOWN_COMMANDS.map(command => ({
    command,
    score: command.startsWith(input)
      ? 0
      : command.includes(input)
        ? 1
        : levenshteinDistance(input, command),
  }))
    .filter(({ command, score }) =>
      command.startsWith(input) ||
      (input.length > 2 && command.includes(input)) ||
      score <= Math.max(2, Math.floor(command.length / 3)),
    )
    .sort((left, right) => left.score - right.score || left.command.localeCompare(right.command))
    .map(({ command }) => command)
    .slice(0, 3)
}

function renderCommandDirectory(): string {
  return ['Available commands:', formatCommandList()].join('\n')
}

function exitWithOutput(output: string, exitCode: number): never {
  process.stderr.write(`${output}\n`)
  process.exit(exitCode)
}

function exitWithCliError(error: CliError, json: boolean, humanOutput?: string): never {
  return exitWithOutput(
    json ? renderError(error, true) : humanOutput ?? renderError(error, false),
    error.exitCode,
  )
}

function exitUnknownCommand(command: string, json: boolean): never {
  const suggestions = findCommandSuggestions(command)
  const lines = [`unknown command "${command}" for "aihelms"`, '']

  if (suggestions.length > 0) {
    lines.push(`Did you mean ${suggestions.length === 1 ? 'this' : 'one of these'}?`)
    lines.push(...suggestions.map(suggestion => `    ${suggestion}`))
    lines.push('')
  }

  lines.push('Usage:  aihelms <command> [flags]', '')
  lines.push(renderCommandDirectory(), '')
  lines.push('Run "aihelms help" for more information.')
  return exitWithCliError(new CliError(`unknown command "${command}" for "aihelms"`, 5), json, lines.join('\n'))
}

function exitUnknownFlag(flag: string, json: boolean): never {
  return exitWithCliError(new CliError(`unknown flag: ${flag}`, 5), json, [
    `unknown flag: ${flag}`,
    '',
    'Usage:  aihelms <command> [flags]',
    '',
    renderCommandDirectory(),
    '',
    'Run "aihelms help" for more information.',
  ].join('\n'))
}

function handleCliParseError(error: unknown, json: boolean): never {
  if (!(error instanceof Error)) {
    return exitWithCliError(new CliError('unexpected failure', 1), json, 'Unexpected error')
  }

  if (error.name === 'CACError') {
    const message = error.message

    if (/unknown option/i.test(message)) {
      const match = message.match(/unknown option ["`]?([^"`]+)["`]?/i)
      return exitUnknownFlag(match?.[1] ?? 'unknown', json)
    }

    if (message.includes('missing required args')) {
      const match = message.match(/command `([^`]+)`/)
      const cmdName = match?.[1] ?? 'command'
      const firstWord = cmdName.split(' ')[0] ?? 'command'

      return exitWithCliError(new CliError('missing required argument', 5), json, [
        'Error: missing required argument',
        '',
        `Usage:  aihelms ${cmdName}`,
        '',
        `Run "aihelms help ${firstWord}" for more information.`,
      ].join('\n'))
    }

    const cleanMessage = message.replace(/`/g, '"')
    return exitWithCliError(new CliError(cleanMessage, 5), json)
  }

  return exitWithCliError(new CliError('unexpected failure', 1), json, `Unexpected error: ${error.message}`)
}

function isJsonRequested(argv: string[]): boolean {
  return argv.includes('--json')
}

function readUnknownCommand(argv: string[]): string | undefined {
  const firstArg = argv[0]
  if (!firstArg || firstArg.startsWith('-') || KNOWN_COMMANDS.includes(firstArg)) {
    return undefined
  }
  return firstArg
}

cli.command('', 'Show help').action(() => runCommand(() => helpCommand([])))

cli
  .command('help [command]', 'Show help')
  .option('--json', 'Output JSON')
  .action((command: string | undefined, options: { json?: boolean }) =>
    runCommand(() => helpCommand(command ? [command] : []), Boolean(options.json)),
  )

cli
  .command('version', 'Show CLI version')
  .option('--json', 'Output JSON')
  .action((options: { json?: boolean }) =>
    runCommand(() => versionCommand(options.json ? ['--json'] : []), Boolean(options.json)),
  )

cli
  .command('login', 'Save registry and CLI token')
  .option('--registry <url>', 'Registry URL')
  .option('--token <token>', 'CLI scoped token')
  .option('--json', 'Output JSON')
  .action((options: { registry?: string; token?: string; json?: boolean }) =>
    runCommand(() => loginCommand(options), Boolean(options.json)),
  )

cli
  .command('logout', 'Remove local token')
  .option('--registry <url>', 'Registry URL')
  .option('--json', 'Output JSON')
  .action((options: { registry?: string; json?: boolean }) =>
    runCommand(() => logoutCommand(options), Boolean(options.json)),
  )

cli
  .command('whoami', 'Verify current token and scopes')
  .option('--registry <url>', 'Registry URL')
  .option('--token <token>', 'CLI scoped token')
  .option('--json', 'Output JSON')
  .action((options: { registry?: string; token?: string; json?: boolean }) =>
    runCommand(() => whoamiCommand(options), Boolean(options.json)),
  )

cli
  .command('search [query]', 'Search published skills')
  .option('--registry <url>', 'Registry URL')
  .option('--token <token>', 'CLI scoped token')
  .option('--category <c>', 'Filter by category')
  .option('--label <l>', 'Filter by label name')
  .option('--sort <sort>', 'Sort: newest|install_count|name')
  .option('--limit <n>', 'Max results', { default: 20 })
  .option('--json', 'Output JSON')
  .action(
    (
      query: string | undefined,
      options: {
        registry?: string
        token?: string
        category?: string
        label?: string
        sort?: string
        limit?: number
        json?: boolean
      },
    ) => runCommand(() => searchCommand(query ?? '', options), Boolean(options.json)),
  )

cli
  .command('install <skill>', 'Install a skill locally (UUID or name)')
  .option('--version <v>', 'Version')
  .option('--scope <scope>', 'Install scope: user or project')
  .option('--agent <profile>', 'Agent profile (repeatable)')
  .option('--dir <path>', 'Install directory')
  .option('--force', 'Overwrite existing')
  .option('--registry <url>', 'Registry URL')
  .option('--token <token>', 'CLI scoped token')
  .option('--json', 'Output JSON')
  .action((skill: string, options: InstallCommandOptions & { agent?: string | string[] }) =>
    runCommand(
      () => installCommand(skill, { ...options, agent: toArray(options.agent) }),
      Boolean(options.json),
    ),
  )

cli
  .command('list', 'List local installs')
  .option('--agent <profile>', 'Filter by agent (repeatable)')
  .option('--dir <path>', 'Filter by directory')
  .option('--registry <url>', 'Registry URL')
  .option('--json', 'Output JSON')
  .action((options: ListCommandOptions & { agent?: string | string[] }) =>
    runCommand(() => listCommand({ ...options, agent: toArray(options.agent) }), Boolean(options.json)),
  )

cli
  .command('remove <skill>', 'Remove a locally installed skill (UUID or name)')
  .option('--agent <profile>', 'Filter by agent (repeatable)')
  .option('--all', 'Remove all targets')
  .option('--registry <url>', 'Registry URL')
  .option('--token <token>', 'CLI scoped token')
  .option('--json', 'Output JSON')
  .action((skill: string, options: RemoveCommandOptions & { agent?: string | string[] }) =>
    runCommand(() => removeCommand(skill, { ...options, agent: toArray(options.agent) }), Boolean(options.json)),
  )

cli
  .command('doctor', 'Scan project skills and rebuild inventory')
  .option('--json', 'Output JSON')
  .action((options: { json?: boolean }) => runCommand(() => doctorCommand(options), Boolean(options.json)))

cli
  .command('publish <skillId> <path>', 'Publish a new skill version for review')
  .option('--version <v>', 'Version (required)')
  .option('--label <l>', 'Version label')
  .option('--change-log <text>', 'Change log')
  .option('--registry <url>', 'Registry URL')
  .option('--token <token>', 'CLI scoped token')
  .option('--json', 'Output JSON')
  .action((skillId: string, path: string, options: PublishCommandOptions) =>
    runCommand(() => publishCommand(skillId, path, options), Boolean(options.json)),
  )

cli.help()

if (require.main === module) {
  const args = process.argv.slice(2)
  const json = isJsonRequested(args)
  const unknownCommand = readUnknownCommand(args)
  if (unknownCommand) {
    exitUnknownCommand(unknownCommand, json)
  }
  try {
    cli.parse(process.argv)
  } catch (error) {
    handleCliParseError(error, json)
  }
}
