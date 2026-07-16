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
  status: 'pending' | 'crawling' | 'crawled' | 'ingesting' | 'ingested' | 'failed'
  pages_total: number
  pages_crawled: number
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
