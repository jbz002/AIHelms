import commonZh from '@aihelms/shared/src/i18n/locales/zh-CN/common.json'
import errorsZh from '@aihelms/shared/src/i18n/locales/zh-CN/errors.json'
import commonEn from '@aihelms/shared/src/i18n/locales/en-US/common.json'
import errorsEn from '@aihelms/shared/src/i18n/locales/en-US/errors.json'
import layoutZh from './zh-CN/layout.json'
import layoutEn from './en-US/layout.json'
import modelSquareZh from './zh-CN/modelSquare.json'
import modelSquareEn from './en-US/modelSquare.json'
import marketZh from './zh-CN/market.json'
import marketEn from './en-US/market.json'
import identityZh from './zh-CN/identity.json'
import identityEn from './en-US/identity.json'
import contributorZh from './zh-CN/contributor.json'
import contributorEn from './en-US/contributor.json'

export const messages = {
  'zh-CN': {
    ...commonZh,
    ...errorsZh,
    ...layoutZh,
    ...modelSquareZh,
    ...marketZh,
    ...identityZh,
    ...contributorZh,
  },
  'en-US': {
    ...commonEn,
    ...errorsEn,
    ...layoutEn,
    ...modelSquareEn,
    ...marketEn,
    ...identityEn,
    ...contributorEn,
  },
}
