import { AihelmsClient } from '../clients/aihelms-client'
import { ConfigStore } from '../stores/config-store'
import { CredentialsStore } from '../stores/credentials-store'
import { EXIT } from '../shared/constants'
import { CliError } from '../shared/errors'

export class AuthService {
  constructor(
    private readonly configStore: ConfigStore,
    private readonly credentialsStore: CredentialsStore,
  ) {}

  async login(registry: string, token?: string): Promise<{ ownerType: string }> {
    if (!token) {
      throw new CliError('token is required', EXIT.usage, {
        next: 'pass --token, set AIHELMS_TOKEN, or run interactive login',
      })
    }
    const user = await new AihelmsClient(registry, token).whoami()
    await this.configStore.setRegistry(registry)
    await this.credentialsStore.setToken(registry, token)
    return { ownerType: user.owner_type }
  }

  async logout(registry: string): Promise<void> {
    await this.credentialsStore.deleteToken(registry)
  }
}
