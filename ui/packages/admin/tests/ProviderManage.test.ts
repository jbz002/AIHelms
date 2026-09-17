import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'
import {
  deleteCredential, deleteProvider, getCredentials, getProviders,
  type Credential, type Provider,
} from '@aihelms/shared'
import ProviderManage from '../src/views/providers/ProviderManage.vue'
import {
  clickNode, createNode, findNode, flushUpdates, nodeText, renderer,
  type RenderNode,
} from './inMemoryVueRenderer'

vi.mock('@aihelms/shared', () => ({
  getProviders: vi.fn(), createProvider: vi.fn(), updateProvider: vi.fn(),
  deleteProvider: vi.fn(), getCredentials: vi.fn(), createCredential: vi.fn(),
  updateCredential: vi.fn(), deleteCredential: vi.fn(), getCredentialModels: vi.fn(),
  getProviderModels: vi.fn(), usePermission: () => ({ hasPermission: () => true }),
}))
vi.mock('../src/components/AccessTestDialog.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/components/ProviderIcon.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/composables/useRegistryMeta', () => ({
  useRegistryMeta: () => ({
    providerOptions: { value: [{ value: 'openai', label: 'OpenAI' }] },
  }),
}))

const provider: Provider = {
  id: 42, name: '测试供应商', provider_type: 'openai', billing_type: 'token',
  monthly_budget: null, monthly_used: '0', is_active: true, description: '',
  config: {}, credential_count: 1, created_at: null, updated_at: null,
}
const credential: Credential = {
  id: 84, credential_name: '测试凭证', provider_id: provider.id,
  provider_name: provider.name, provider_type: provider.provider_type,
  credential_values: {}, credential_info: {}, litellm_synced: true,
  is_active: true, deployment_count: 1, created_at: null, updated_at: null,
}
const credentialConflict = '该凭证被部署引用，请先解除关联'
const providerConflict = '该供应商下有凭证，请先删除或迁移凭证'

describe('ProviderManage deletion feedback', () => {
  let root: RenderNode
  let app: App

  function getNode(matches: (node: RenderNode) => boolean): RenderNode {
    const node = findNode(root, matches)
    if (!node) throw new Error('Expected rendered node was not found')
    return node
  }

  function button(label: string): RenderNode {
    return getNode(node => node.tag === 'button' && nodeText(node) === label)
  }

  function dialog(): RenderNode | undefined {
    return findNode(root, node => node.props.role === 'dialog')
  }

  async function selectProvider(): Promise<void> {
    await clickNode(getNode(node => node.tag === 'div' && typeof node.props.onClick === 'function'
      && nodeText(node).includes(provider.name)))
  }

  beforeEach(async () => {
    vi.resetAllMocks()
    vi.mocked(getProviders).mockResolvedValue({ items: [provider], total: 1, page: 1, page_size: 100 })
    vi.mocked(getCredentials).mockResolvedValue({ items: [credential], total: 1, page: 1, page_size: 100 })
    vi.mocked(deleteProvider).mockResolvedValue(null)
    vi.mocked(deleteCredential).mockResolvedValue(null)
    root = createNode('root')
    app = renderer.createApp(ProviderManage)
    app.mount(root)
    await flushUpdates()
    await selectProvider()
  })

  afterEach(() => app.unmount())

  it('should keep the credential dialog open and show the exact conflict reason', async () => {
    await clickNode(getNode(node => node.props['data-testid'] === 'delete-credential-button'))
    expect(dialog()).toBeDefined()
    vi.mocked(deleteCredential).mockRejectedValueOnce(new Error(credentialConflict))
    await clickNode(button('确认'))
    expect(dialog()).toBeDefined()
    expect(nodeText(getNode(node => node.props.role === 'alert'))).toBe(credentialConflict)
    expect(findNode(root, node => node.props['data-testid'] === 'delete-credential-button')).toBeDefined()
    expect(getCredentials).toHaveBeenCalledTimes(1)
  })

  it('should keep the provider dialog open and show its conflict reason', async () => {
    await clickNode(getNode(node => node.props['data-testid'] === 'delete-provider-button'))
    expect(dialog()).toBeDefined()
    vi.mocked(deleteProvider).mockRejectedValueOnce(new Error(providerConflict))
    await clickNode(button('确认'))
    expect(dialog()).toBeDefined()
    expect(nodeText(getNode(node => node.props.role === 'alert'))).toBe(providerConflict)
    expect(getProviders).toHaveBeenCalledTimes(1)
  })

  it('should refresh credentials after a successful deletion', async () => {
    await clickNode(getNode(node => node.props['data-testid'] === 'delete-credential-button'))
    await clickNode(button('确认'))
    expect(deleteCredential).toHaveBeenCalledWith(credential.id)
    expect(getCredentials).toHaveBeenCalledTimes(2)
    expect(dialog()).toBeUndefined()
  })
})
