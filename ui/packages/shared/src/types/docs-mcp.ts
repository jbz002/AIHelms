import type { HttpMethod, Operation } from './openapi-subset'

export interface DocsMcpStats {
  totalChunks: number
  libraryCount: number
  versionCount: number
  totalPages: number
}

export interface DocsMcpJobProgress {
  pagesScraped: number
  totalPages: number
  totalDiscovered: number
  currentUrl: string
  depth: number
  maxDepth: number
}

export interface DocsMcpJob {
  id: string
  library: string
  version: string | null
  status: string
  progress: DocsMcpJobProgress | null
  error: { message: string } | null
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
  sourceUrl: string | null
  progressPages?: number
  progressMaxPages?: number
  errorMessage?: string | null
}

export interface DocsMcpVersionCounts {
  documents: number
  uniqueUrls: number
}

export interface DocsMcpVersionProgress {
  pages: number
  maxPages: number
}

export interface DocsMcpVersion {
  id: number
  ref: { library: string; version: string }
  status: string
  progress?: DocsMcpVersionProgress
  counts: DocsMcpVersionCounts
  indexedAt: string | null
  sourceUrl?: string | null
}

export interface DocsMcpLibrary {
  library: string
  versions: DocsMcpVersion[]
}

export interface DocsMcpSearchResult {
  url: string
  content: string
  score: number | null
  mimeType?: string | null
  sourceMimeType?: string | null
}

export interface DocsMcpScrapeOptions {
  maxPages?: number
  maxDepth?: number
  scope?: 'subpages' | 'hostname' | 'domain'
  followRedirects?: boolean
  maxConcurrency?: number
  ignoreErrors?: boolean
  excludeSelectors?: string[]
  includePatterns?: string[]
  excludePatterns?: string[]
  preserveHashes?: boolean
  scrapeMode?: 'fetch' | 'playwright' | 'auto'
  headers?: Record<string, string>
}

export interface DocsMcpCreateJobParams {
  url: string
  library: string
  version: string
  options: DocsMcpScrapeOptions
}

export interface DocsMcpDbVersion {
  id: number
  library_id: number
  name: string | null
  created_at: string
  status: string
  progress_pages: number
  progress_max_pages: number
  error_message: string | null
  started_at: string | null
  updated_at: string
  source_url: string | null
  scraper_options: string | null
  library_name: string
}

export interface DocsMcpStoredScraperOptions {
  sourceUrl: string
  options: DocsMcpScrapeOptions
}

export interface DocsMcpFetchUrlResult {
  content: string
}

export interface DocUploadRecord {
  id: number
  library: string
  version: string
  file_name: string
  file_size: number
  content_type: string
  status: 'pending' | 'extracting' | 'extracted' | 'ingesting' | 'completed' | 'failed'
  chunk_count: number
  error_message: string
  extracted_content_preview: string
  created_by: number | null
  created_at: string
  finished_at: string | null
}

export interface DocUploadListResult {
  items: DocUploadRecord[]
  total: number
  page: number
  page_size: number
}

export interface CrawlTask {
  id: number
  job_id: string
  library: string
  version: string
  source_url: string
  status: 'pending' | 'crawling' | 'crawled' | 'ingesting' | 'ingested' | 'failed' | 'paused'
  paused_from: string | null
  pages_total: number
  pages_crawled: number
  pages_ingested: number
  current_url: string
  error_message: string
  created_by: number | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface CrawledPage {
  id: number
  crawl_task_id: number
  url: string
  title: string
  source_content_type: string
  content_type: string
  text_content: string
  chunks_count: number
  depth: number
  created_at: string
}

export interface CrawlTaskListResult {
  items: CrawlTask[]
  total: number
  page: number
  page_size: number
}

export interface CrawlPageListResult {
  items: CrawledPage[]
  total: number
  page: number
  page_size: number
}

export type DocTaskSource = 'external_crawl' | 'internal_upload'
export type DocTaskStatus =
  | 'pending'
  | 'processing'
  | 'ready'
  | 'ingesting'
  | 'ingested'
  | 'failed'
  | 'duplicate'
  | 'paused'

export interface DocTask {
  key: string
  source: DocTaskSource
  raw_id: number
  library: string
  version: string
  title: string
  subtitle: string
  status_raw: string
  status: DocTaskStatus
  paused_from: string | null
  progress_text: string
  current_url: string
  extracted_content_preview: string
  error_message: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  can_ingest: boolean
  is_partial: boolean
  pages_backfilled: number
  pages_empty: number
}

export interface DocTaskListResult {
  items: DocTask[]
  total: number
  page: number
  page_size: number
}

export interface Document {
  id: number
  title: string
  content: string
  library: string
  version: string
  source_type: string
  source_id: number | null
  chunk_count: number
  ingest_status: 'pending' | 'ingesting' | 'ingested' | 'failed' | 'duplicate'
  content_hash: string
  error_message: string
  created_by: number | null
  created_at: string
  updated_at: string
  metadata: Record<string, unknown>
}

export interface DocumentApiExtractStatus {
  id: number
  spec_id: string
  document_id: number
  status: 'queued' | 'running' | 'completed' | 'failed'
  model_id: number | null
  model_name: string
  endpoint_count: number
  prompt_tokens: number
  completion_tokens: number
  summary: { progress?: { value: number; completed: number; total: number; step: string }; warning?: string }
  error_message: string
  created_by: number | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface DocumentListResult {
  items: Document[]
  total: number
  page: number
  page_size: number
}

export interface IngestStats {
  by_status: Record<string, number>
  total_documents: number
  total_chunks: number
  library: string | null
}

export interface IngestBatchParams {
  library?: string
  source_type?: string
}

export interface DocumentDashboardSummaryGlobal {
  by_source: Record<string, number>
  total_documents: number
}

export interface DocumentDashboardLibraryBreakdown {
  by_source: Record<string, number>
  by_status: Record<string, number>
  total_documents: number
}

export interface DocumentDashboardSummary {
  global: DocumentDashboardSummaryGlobal
  by_library: Record<string, DocumentDashboardLibraryBreakdown>
}

// ── 库级接口提取与分类 ──

export interface LibraryBatchExtractStatus {
  id: number
  job_id: string
  library: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  model_id: number | null
  model_name: string
  total_documents: number
  completed_documents: number
  failed_documents: number
  skipped_documents: number
  total_endpoints: number
  summary: { progress?: { value: number; completed: number; total: number; step: string } }
  error_message: string
  created_by: number | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface LibraryClassifyStatus {
  id: number
  job_id: string
  library: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  model_id: number | null
  model_name: string
  endpoint_count: number
  category_count: number
  prompt_tokens: number
  completion_tokens: number
  categories: string[]
  summary: { progress?: { value: number; step: string } }
  error_message: string
  created_by: number | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface LibraryEndpoint {
  id: number
  document_id: number
  method: HttpMethod
  path: string
  summary: string
  category: string
  operation: Operation
}

export interface LibraryInterfacesResult {
  library: string
  total: number
  endpoints: LibraryEndpoint[]
}

// ── AI 摘要搜索（SSE 流式）──

export interface DocsMcpAskSource {
  url: string
  score: number | null
}

export interface DocsMcpAskDoneMeta {
  finish_reason?: string
  model?: string
  prompt_tokens?: number
  completion_tokens?: number
}

export interface DocsMcpAskStreamHandlers {
  onSources: (sources: DocsMcpAskSource[]) => void
  onDelta: (content: string) => void
  onDone: (meta: DocsMcpAskDoneMeta) => void
  onError: (message: string) => void
}
