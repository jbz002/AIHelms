import { request } from './request'
import type {
  DocsMcpStats,
  DocsMcpJob,
  DocsMcpLibrary,
  DocsMcpSearchResult,
  DocsMcpCreateJobParams,
  DocsMcpDbVersion,
  DocsMcpStoredScraperOptions,
  DocsMcpScrapeOptions,
} from '../types/docs-mcp'

export function getDocsMcpStats() {
  return request<DocsMcpStats>('/api/v1/docs-mcp/stats')
}

export function getDocsMcpJobs(status?: string) {
  return request<DocsMcpJob[]>('/api/v1/docs-mcp/jobs', {
    params: status ? { status } : undefined,
  })
}

export function createDocsMcpJob(params: DocsMcpCreateJobParams) {
  return request<{ jobId: string }>('/api/v1/docs-mcp/jobs', {
    method: 'POST',
    body: params,
  })
}

export function cancelDocsMcpJob(jobId: string) {
  return request<void>('/api/v1/docs-mcp/jobs/{jobId}/cancel'.replace('{jobId}', jobId), {
    method: 'POST',
  })
}

export function clearCompletedDocsMcpJobs() {
  return request<{ count: number }>('/api/v1/docs-mcp/jobs/clear-completed', {
    method: 'POST',
  })
}

export function refreshDocsMcpVersion(jobId: string, body: { library: string; version: string | null; options?: unknown }) {
  return request<{ jobId: string }>('/api/v1/docs-mcp/jobs/{jobId}/refresh'.replace('{jobId}', jobId), {
    method: 'POST',
    body,
  })
}

export function getDocsMcpLibraries() {
  return request<DocsMcpLibrary[]>('/api/v1/docs-mcp/libraries')
}

export function getDocsMcpLibraryDetail(libraryName: string) {
  return request<DocsMcpLibrary>('/api/v1/docs-mcp/libraries/{name}'.replace('{name}', libraryName))
}

export function searchDocsMcp(libraryName: string, query: string, version?: string, limit?: number) {
  return request<DocsMcpSearchResult[]>('/api/v1/docs-mcp/libraries/{name}/search'.replace('{name}', libraryName), {
    params: { query, version, limit } as Record<string, string | number | undefined>,
  })
}

export function deleteDocsMcpVersion(libraryName: string, version: string) {
  return request<void>('/api/v1/docs-mcp/libraries/{name}/versions/{version}'
    .replace('{name}', libraryName)
    .replace('{version}', version), {
    method: 'DELETE',
  })
}

export function getDocsMcpEventSourceUrl(): string {
  return '/api/v1/docs-mcp/events'
}

export function getDocsMcpJobDetail(jobId: string) {
  return request<DocsMcpJob>('/api/v1/docs-mcp/jobs/{jobId}'.replace('{jobId}', jobId))
}

export function checkDocsMcpLibraryExists(libraryName: string) {
  return request<{ exists: boolean }>('/api/v1/docs-mcp/libraries/{name}/exists'.replace('{name}', libraryName))
}

export function getDocsMcpVersions(status?: string) {
  return request<DocsMcpDbVersion[]>('/api/v1/docs-mcp/versions', {
    params: status ? { status } : undefined,
  })
}

export function findDocsMcpVersionsByUrl(url: string) {
  return request<DocsMcpDbVersion[]>('/api/v1/docs-mcp/versions/by-url', {
    params: { url },
  })
}

export function getDocsMcpVersionOptions(versionId: number) {
  return request<DocsMcpStoredScraperOptions | null>('/api/v1/docs-mcp/versions/{versionId}/options'.replace('{versionId}', String(versionId)))
}

export function updateDocsMcpVersionOptions(versionId: number, options: DocsMcpScrapeOptions) {
  return request<void>('/api/v1/docs-mcp/versions/{versionId}/options'.replace('{versionId}', String(versionId)), {
    method: 'PUT',
    body: options,
  })
}

export function deleteDocsMcpVersionDocuments(libraryName: string, version: string) {
  return request<void>('/api/v1/docs-mcp/libraries/{name}/versions/{version}/documents'
    .replace('{name}', libraryName)
    .replace('{version}', version), {
    method: 'DELETE',
  })
}
