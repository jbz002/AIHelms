import { request } from './request'
import { getCurrentLocale } from '../i18n'
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
  DocumentLibrary,
  DocumentLibraryListResult,
  IngestStats,
  IngestBatchParams,
  DocumentDashboardSummary,
  DocumentApiExtractStatus,
  LibraryBatchExtractStatus,
  LibraryClassifyStatus,
  LibraryEndpoint,
  LibraryInterfacesResult,
  DocsMcpAskSource,
  DocsMcpAskDoneMeta,
  DocsMcpAskStreamHandlers,
} from '../types/docs-mcp'
import type { OpenApiSpec, ProxyRequestPayload, ProxyResult } from '../types/openapi-subset'

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

function parseSseFrame(frame: string): { event: string; data: string } | null {
  let event = ''
  let data = ''
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data += line.slice(5).trim()
    }
  }
  if (!event) return null
  return { event, data }
}

function dispatchSseEvent(event: string, data: string, handlers: DocsMcpAskStreamHandlers): void {
  let payload: unknown = null
  if (data) {
    try {
      payload = JSON.parse(data)
    } catch {
      return
    }
  }
  switch (event) {
    case 'sources':
      handlers.onSources(Array.isArray(payload) ? (payload as DocsMcpAskSource[]) : [])
      break
    case 'delta':
      handlers.onDelta((payload as { content?: string })?.content ?? '')
      break
    case 'done':
      handlers.onDone((payload as DocsMcpAskDoneMeta) ?? {})
      break
    case 'error':
      handlers.onError((payload as { message?: string })?.message ?? '未知错误')
      break
    default:
      break
  }
}

export async function streamDocsMcpAsk(
  libraryName: string,
  body: { query: string; version?: string },
  handlers: DocsMcpAskStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const url = '/api/v1/docs-mcp/libraries/{name}/ask'.replace('{name}', libraryName)
  const token = localStorage.getItem('aihelms_token')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept-Language': getCurrentLocale(),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  let resp: Response
  try {
    resp = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body), signal })
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') return
    handlers.onError('网络错误，请稍后重试')
    return
  }

  if (resp.status === 401) {
    handlers.onError('未认证或 token 已过期')
    return
  }
  if (!resp.ok || !resp.body) {
    let message = `请求失败 (${resp.status})`
    try {
      const text = await resp.text()
      const json = JSON.parse(text) as { message?: string }
      if (json.message) message = json.message
    } catch {
      // 非 JSON 错误体，保留默认 message
    }
    handlers.onError(message)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const parsed = parseSseFrame(frame)
        if (!parsed) continue
        dispatchSseEvent(parsed.event, parsed.data, handlers)
      }
    }
    if (buffer.trim()) {
      const parsed = parseSseFrame(buffer)
      if (parsed) dispatchSseEvent(parsed.event, parsed.data, handlers)
    }
  } catch (e) {
    if ((e as Error)?.name !== 'AbortError') {
      handlers.onError('读取响应流失败')
    }
  }
}

export function deleteDocsMcpVersion(libraryName: string, version: string) {
  const versionParam = version || 'latest'
  return request<void>('/api/v1/docs-mcp/libraries/{name}/versions/{version}'
    .replace('{name}', libraryName)
    .replace('{version}', versionParam), {
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
  const versionParam = version || 'latest'
  return request<void>('/api/v1/docs-mcp/libraries/{name}/versions/{version}/documents'
    .replace('{name}', libraryName)
    .replace('{version}', versionParam), {
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

export function uploadDocumentsBatch(
  library: string,
  files: File[],
  version?: string,
  autoIngest?: boolean,
) {
  const formData = new FormData()
  formData.append('library', library)
  for (const f of files) formData.append('files', f)
  if (version) formData.append('version', version)
  if (autoIngest !== undefined) formData.append('auto_ingest', String(autoIngest))
  return request<{ items: DocUploadRecord[]; total: number }>('/api/v1/docs-mcp/upload-batch', {
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

export function pauseCrawlTask(taskId: number) {
  return request<CrawlTask>('/api/v1/docs-mcp/crawl-tasks/{taskId}/pause'.replace('{taskId}', String(taskId)), {
    method: 'POST',
  })
}

export function resumeCrawlTask(taskId: number) {
  return request<CrawlTask>('/api/v1/docs-mcp/crawl-tasks/{taskId}/resume'.replace('{taskId}', String(taskId)), {
    method: 'POST',
  })
}

export function getDocTasks(source?: DocTaskSource, status?: DocTaskStatus, page?: number, pageSize?: number, dateRange?: string, library?: string) {
  return request<DocTaskListResult>('/api/v1/docs-mcp/tasks', {
    params: { source, status, page, page_size: pageSize, date_range: dateRange, library } as Record<string, string | number | undefined>,
  })
}

export function deleteUploadRecord(recordId: number) {
  return request<void>(`/api/v1/docs-mcp/uploads/${recordId}`, {
    method: 'DELETE',
  })
}

export function getUploadRecordContent(recordId: number) {
  return request<{ content: string }>(`/api/v1/docs-mcp/uploads/${recordId}/content`)
}

// ── 统一文档表 CRUD ──

export function getDocuments(
  library?: string,
  sourceType?: string,
  ingestStatus?: string,
  page?: number,
  pageSize?: number,
  version?: string,
  title?: string,
) {
  return request<DocumentListResult>('/api/v1/documents', {
    params: {
      library,
      source_type: sourceType,
      ingest_status: ingestStatus,
      version,
      page,
      page_size: pageSize,
      title,
    } as Record<string, string | number | undefined>,
  })
}

export function getDocument(documentId: number) {
  return request<Document>(`/api/v1/documents/${documentId}`)
}

export function getDocumentSpec(documentId: number) {
  return request<OpenApiSpec>(`/api/v1/documents/${documentId}/spec`)
}

export function proxyDocumentRequest(documentId: number, payload: ProxyRequestPayload) {
  return request<ProxyResult>(`/api/v1/documents/${documentId}/proxy`, {
    method: 'POST',
    body: payload,
  })
}

export function getDocumentExtractStatus(documentId: number) {
  return request<DocumentApiExtractStatus | null>(
    `/api/v1/documents/${documentId}/extract-status`,
  )
}

export function extractDocumentInterfaces(documentId: number) {
  return request<DocumentApiExtractStatus>(
    `/api/v1/documents/${documentId}/extract-interfaces`,
    { method: 'POST' },
  )
}

// ── 库级接口提取与分类 ──

export function extractLibraryInterfaces(libraryName: string) {
  return request<LibraryBatchExtractStatus>(
    `/api/v1/document-libraries/${encodeURIComponent(libraryName)}/extract-interfaces`,
    { method: 'POST' },
  )
}

export function getLibraryExtractStatus(libraryName: string) {
  return request<LibraryBatchExtractStatus | null>(
    `/api/v1/document-libraries/${encodeURIComponent(libraryName)}/extract-status`,
  )
}

export function classifyLibraryInterfaces(libraryName: string) {
  return request<LibraryClassifyStatus>(
    `/api/v1/document-libraries/${encodeURIComponent(libraryName)}/classify-interfaces`,
    { method: 'POST' },
  )
}

export function getLibraryClassifyStatus(libraryName: string) {
  return request<LibraryClassifyStatus | null>(
    `/api/v1/document-libraries/${encodeURIComponent(libraryName)}/classify-status`,
  )
}

export function getLibraryInterfaces(libraryName: string) {
  return request<LibraryInterfacesResult>(
    `/api/v1/document-libraries/${encodeURIComponent(libraryName)}/interfaces`,
  )
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

export function getDocumentStats(library?: string, version?: string) {
  return request<IngestStats>('/api/v1/documents/stats', {
    params: { library, version },
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

export function getDocumentDashboardSummary() {
  return request<DocumentDashboardSummary>('/api/v1/documents/dashboard-summary')
}

// ── 平台文档库(document_libraries)列表与创建 ──

export function listLibraries(page = 1, pageSize = 50, keyword = '') {
  return request<DocumentLibraryListResult>('/api/v1/document-libraries', {
    params: { page, page_size: pageSize, keyword },
  })
}

export function createLibrary(name: string, description = '') {
  return request<DocumentLibrary>('/api/v1/document-libraries', {
    method: 'POST',
    body: { name, description },
  })
}

export function updateLibrary(
  libraryId: number,
  params: { name?: string; description?: string },
) {
  return request<DocumentLibrary>(`/api/v1/document-libraries/${libraryId}`, {
    method: 'PUT',
    body: params,
  })
}

export function deleteLibrary(libraryId: number) {
  return request<void>(`/api/v1/document-libraries/${libraryId}`, {
    method: 'DELETE',
  })
}
