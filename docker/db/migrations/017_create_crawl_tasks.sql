-- 017: 爬取任务和爬取页面表（crawl-only 解耦模式）

CREATE TABLE IF NOT EXISTS aihelms.crawl_tasks (
    id BIGSERIAL PRIMARY KEY,
    job_id VARCHAR(100) NOT NULL,
    library VARCHAR(200) NOT NULL,
    version VARCHAR(200) DEFAULT '',
    source_url TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    pages_total INT DEFAULT 0,
    pages_crawled INT DEFAULT 0,
    error_message TEXT DEFAULT '',
    scraper_options JSONB DEFAULT '{}',
    created_by BIGINT REFERENCES aihelms.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_crawl_tasks_library ON aihelms.crawl_tasks(library);
CREATE INDEX IF NOT EXISTS idx_crawl_tasks_status ON aihelms.crawl_tasks(status);
CREATE INDEX IF NOT EXISTS idx_crawl_tasks_job_id ON aihelms.crawl_tasks(job_id);

CREATE TABLE IF NOT EXISTS aihelms.crawled_pages (
    id BIGSERIAL PRIMARY KEY,
    crawl_task_id BIGINT NOT NULL REFERENCES aihelms.crawl_tasks(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title VARCHAR(500) DEFAULT '',
    source_content_type VARCHAR(100) DEFAULT '',
    content_type VARCHAR(100) DEFAULT '',
    text_content TEXT DEFAULT '',
    links TEXT[] DEFAULT '{}',
    chunks JSONB DEFAULT '[]',
    depth INT DEFAULT 0,
    etag VARCHAR(200),
    last_modified VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(crawl_task_id, url)
);

CREATE INDEX IF NOT EXISTS idx_crawled_pages_task_id ON aihelms.crawled_pages(crawl_task_id);
