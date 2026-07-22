import { EXIT } from '../shared/constants'
import { CliError } from '../shared/errors'

/** AIHelms 私有化部署无固定公共 registry：--registry > AIHELMS_REGISTRY env > config，全空则报错。 */
export function resolveRegistry(
  args: { registry?: string },
  env: NodeJS.ProcessEnv,
  config: { registry?: string },
): string {
  const registry = args.registry || env.AIHELMS_REGISTRY || config.registry
  if (!registry) {
    throw new CliError(
      '未配置 registry，请运行 `aihelms login --registry <url> --token <sk_cli_...>`',
      EXIT.usage,
      { next: 'login 时指定 --registry，或设置 AIHELMS_REGISTRY 环境变量' },
    )
  }
  return registry.replace(/\/+$/, '')
}

export function resolveToken(
  args: { token?: string },
  env: NodeJS.ProcessEnv,
  storedToken?: string,
): string | undefined {
  return args.token || env.AIHELMS_TOKEN || storedToken
}
