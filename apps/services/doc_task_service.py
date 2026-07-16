"""文档任务统一视图：合并爬取与上传任务列表与状态。"""

from sqlalchemy.ext.asyncio import AsyncSession

from repositories import crawl_task_repo, doc_upload_repo

# crawl 原态 → 统一状态
_CRAWL_STATUS_MAP: dict[str, str] = {
    "pending": "pending",
    "crawling": "processing",
    "crawled": "ready",
    "ingesting": "ingesting",
    "ingested": "ingested",
    "failed": "failed",
}

# upload 原态 → 统一状态
_UPLOAD_STATUS_MAP: dict[str, str] = {
    "pending": "pending",
    "extracting": "processing",
    "extracted": "ready",
    "ingesting": "ingesting",
    "completed": "ingested",
    "failed": "failed",
}

# 单表拉取上限（任务记录量级小，内存合并即可）
_FETCH_CAP = 1000


def _fmt_dt(dt: object) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


def _format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _from_crawl(task: object) -> dict:
    return {
        "key": f"crawl-{task.id}",
        "source": "external_crawl",
        "raw_id": task.id,
        "library": task.library,
        "version": task.version,
        "title": task.library,
        "subtitle": task.source_url,
        "status_raw": task.status,
        "status": _CRAWL_STATUS_MAP.get(task.status, task.status),
        "progress_text": f"{task.pages_crawled}/{task.pages_total} 页",
        "extracted_content_preview": "",
        "error_message": task.error_message or "",
        "created_at": _fmt_dt(task.created_at),
        "started_at": _fmt_dt(task.started_at),
        "finished_at": _fmt_dt(task.finished_at),
        "can_ingest": task.status == "crawled",
    }


def _from_upload(record: object) -> dict:
    progress = f"{record.chunk_count} 块" if record.chunk_count else ""
    return {
        "key": f"upload-{record.id}",
        "source": "internal_upload",
        "raw_id": record.id,
        "library": record.library,
        "version": record.version,
        "title": record.file_name,
        "subtitle": f"{_format_file_size(record.file_size)} · {record.content_type}",
        "status_raw": record.status,
        "status": _UPLOAD_STATUS_MAP.get(record.status, record.status),
        "progress_text": progress,
        "extracted_content_preview": (record.extracted_content or "")[:200],
        "error_message": record.error_message or "",
        "created_at": _fmt_dt(record.created_at),
        "started_at": None,
        "finished_at": _fmt_dt(record.finished_at),
        "can_ingest": record.status == "extracted",
    }


async def list_tasks(
    session: AsyncSession,
    source: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """合并查询 crawl + upload 任务，按创建时间倒序统一分页。"""
    unified: list[dict] = []

    if source in (None, "external_crawl"):
        tasks = await crawl_task_repo.list_tasks(session, None, 1, _FETCH_CAP)
        unified.extend(_from_crawl(t) for t in tasks)

    if source in (None, "internal_upload"):
        records = await doc_upload_repo.list_all(session, 1, _FETCH_CAP)
        unified.extend(_from_upload(r) for r in records)

    if status:
        unified = [u for u in unified if u["status"] == status]

    unified.sort(key=lambda x: x["created_at"] or "", reverse=True)

    total = len(unified)
    start = (page - 1) * page_size
    page_items = unified[start : start + page_size]

    return {
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
