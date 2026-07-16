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
  DocsMcpFetchUrlResult,
  DocUploadRecord,
  DocUploadListResult,
  CrawlTask,
  CrawlTaskListResult,
  CrawlPageListResult,
  DocTaskSource,
  DocTaskStatus,
  DocTaskListResult,
  Document,
  DocumentListResult,
  IngestStats,
  IngestBatchParams,
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

export function fetchDocsMcpUrl(url: string, followRedirects = true) {
  return request<DocsMcpFetchUrlResult>('/api/v1/docs-mcp/fetch-url', {
    method: 'POST',
    body: { url, followRedirects },
  })
}

export function uploadDocument(library: string, file: File, version?: string, autoIngest?: boolean) {
  const formData = new FormData()
  formData.append('library', library)
  formData.append('file', file)
  if (version) formData.append('version', version)
  if (autoIngest !== undefined) formData.append('auto_ingest', String(autoIngest))
  return request<DocUploadRecord>('/api/v1/docs-mcp/upload', {
    method: 'POST',
    body: formData,
  })
}

export function ingestUploadRecord(recordId: number) {
  return request<DocUploadRecord>(`/api/v1/docs-mcp/uploads/${recordId}/ingest`, {
    method: 'POST',
  })
}

export function getDocUploadRecords(library?: string, page = 1, pageSize = 20) {
  return request<DocUploadListResult>('/api/v1/docs-mcp/uploads', {
    params: { library, page, page_size: pageSize } as Record<string, string | number | undefined>,
  })
}

export function createCrawlTask(params: { url: string; library: string; version: string; options: DocsMcpScrapeOptions; auto_ingest?: boolean }) {
  return request<CrawlTask>('/api/v1/docs-mcp/crawl-tasks', {
    method: 'POST',
    body: params,
  })
}

export function getCrawlTasks(status?: string, page?: number, pageSize?: number) {
  return request<CrawlTaskListResult>('/api/v1/docs-mcp/crawl-tasks', {
    params: { status, page, page_size: pageSize } as Record<string, string | number | undefined>,
  })
}

export function getCrawlTask(taskId: number) {
  return request<CrawlTask>('/api/v1/docs-mcp/crawl-tasks/{taskId}'.replace('{taskId}', String(taskId)))
}

export function getCrawlPages(taskId: number, page?: number, pageSize?: number) {
  return request<CrawlPageListResult>('/api/v1/docs-mcp/crawl-tasks/{taskId}/pages'.replace('{taskId}', String(taskId)), {
    params: { page, page_size: pageSize } as Record<string, string | number | undefined>,
  })
}

export function ingestCrawlTask(taskId: number) {
  return request<CrawlTask>('/api/v1/docs-mcp/crawl-tasks/{taskId}/ingest'.replace('{taskId}', String(taskId)), {
    method: 'POST',
  })
}

export function deleteCrawlTask(taskId: number) {
  return request<void>('/api/v1/docs-mcp/crawl-tasks/{taskId}'.replace('{taskId}', String(taskId)), {
    method: 'DELETE',
  })
}

export function getDocTasks(source?: DocTaskSource, status?: DocTaskStatus, page?: number, pageSize?: number) {
  return request<DocTaskListResult>('/api/v1/docs-mcp/tasks', {
    params: { source, status, page, page_size: pageSize } as Record<string, string | number | undefined>,
  })
}

export function deleteUploadRecord(recordId: number) {
  return request<void>(`/api/v1/docs-mcp/uploads/${recordId}`, {
    method: 'DELETE',
  })
}

// ── 统一文档表 CRUD ──

export function getDocuments(
  library?: string,
  sourceType?: string,
  ingestStatus?: string,
  page?: number,
  pageSize?: number,
) {
  return request<DocumentListResult>('/api/v1/documents', {
    params: {
      library,
      source_type: sourceType,
      ingest_status: ingestStatus,
      page,
      page_size: pageSize,
    } as Record<string, string | number | undefined>,
  })
}

export function getDocument(documentId: number) {
  return request<Document>(`/api/v1/documents/${documentId}`)
}

export function updateDocument(
  documentId: number,
  params: { title?: string; content?: string; metadata_?: Record<string, unknown> },
) {
  return request<Document>(`/api/v1/documents/${documentId}`, {
    method: 'PUT',
    body: params,
  })
}

export function deleteDocument(documentId: number) {
  return request<void>(`/api/v1/documents/${documentId}`, {
    method: 'DELETE',
  })
}

// ── 文档入库 ──

export function getDocumentStats(library?: string) {
  return request<IngestStats>('/api/v1/documents/stats', {
    params: library ? { library } : undefined,
  })
}

export function ingestDocument(documentId: number) {
  return request<{ task_id: string }>(`/api/v1/documents/${documentId}/ingest`, {
    method: 'POST',
  })
}

export function ingestDocumentBatch(params?: IngestBatchParams) {
  return request<{ task_id: string }>('/api/v1/documents/ingest-batch', {
    method: 'POST',
    body: params || {},
  })
}
