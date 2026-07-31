import { request } from './request'
import type { TokenData, CurrentUser } from '../types/auth'

export function loginOAuth2(code: string): Promise<TokenData> {
  return request<TokenData>('/api/v1/auth/login/oauth2', {
    method: 'POST',
    body: { code },
    silent: true,
  })
}

export function loginTicket(ticket: string): Promise<TokenData> {
  return request<TokenData>('/api/v1/auth/login/ticket', {
    method: 'POST',
    body: { ticket },
    silent: true,
  })
}

export function getMe(): Promise<CurrentUser> {
  return request<CurrentUser>('/api/v1/auth/me')
}
