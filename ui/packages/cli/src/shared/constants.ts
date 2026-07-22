/** AIHelms 私有化部署无固定公共 registry，不设硬编码默认值。 */
export const CLI_VERSION = '0.1.0'
export const CLI_PACKAGE_NAME = '@aihelms/cli'

export const EXIT = {
  generic: 1,
  auth: 2,
  network: 3,
  filesystem: 4,
  usage: 5,
  validation: 6,
} as const
