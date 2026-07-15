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
