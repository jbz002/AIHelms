import type { HttpMethod } from '../types/openapi-subset'

export interface CurlInput {
  method: HttpMethod
  url: string
  headers?: Record<string, string>
  queryParams?: Record<string, string>
  body?: string | null
}

function shellQuote(value: string): string {
  // 单引号包裹；内嵌单引号用 '\'' 转义
  return `'${value.replace(/'/g, `'\\''`)}'`
}

function appendQuery(url: string, queryParams?: Record<string, string>): string {
  if (!queryParams) return url
  const search = new URLSearchParams()
  Object.entries(queryParams).forEach(([key, value]) => {
    if (value !== undefined && value !== '') search.append(key, value)
  })
  const query = search.toString()
  if (!query) return url
  return url.includes('?') ? `${url}&${query}` : `${url}?${query}`
}

/** 由 method/url/headers/query/body 组装 curl 命令串（仅 curl，参考 scalar snippetz 行为）。 */
export function buildCurl(input: CurlInput): string {
  const { method, url, headers, queryParams, body } = input
  const parts: string[] = ['curl']
  parts.push(shellQuote(appendQuery(url, queryParams)))
  if (method !== 'get') parts.push(`-X ${method.toUpperCase()}`)
  Object.entries(headers ?? {}).forEach(([key, value]) => {
    parts.push(`-H ${shellQuote(`${key}: ${value}`)}`)
  })
  if (body) parts.push(`-d ${shellQuote(body)}`)
  return parts.join(' \\\n  ')
}
