import { request } from './request'
import type { TokenData, CurrentUser, ChangePasswordParams } from '../types/auth'

export function login(username: string, password: string): Promise<TokenData> {
  return request<TokenData>('/api/v1/auth/login', {
    method: 'POST',
    body: { username, password },
    silent: true,
  })
}

export function loginOAuth2(code: string): Promise<TokenData> {
  return request<TokenData>('/api/v1/auth/login/oauth2', {
    method: 'POST',
    body: { code },
    silent: true,
  })
}

export function getMe(): Promise<CurrentUser> {
  return request<CurrentUser>('/api/v1/auth/me')
}

export function changePassword(params: ChangePasswordParams): Promise<null> {
  return request<null>('/api/v1/auth/password', {
    method: 'PUT',
    body: params,
  })
}
