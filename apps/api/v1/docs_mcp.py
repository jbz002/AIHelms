"""API文档管理 — docs-mcp-server 反向代理路由。"""

import logging

import httpx
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse

from core.config import settings
from core.database import async_session
from core.deps import get_current_user, get_db
from services import doc_upload_service
from services.docs_mcp_client import DocsMcpError, docs_mcp_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/docs-mcp", tags=["AI实验室"])


@router.get("/stats", summary="获取文档管理统计")
async def get_stats(_: dict = Depends(get_current_user)):
    """聚合统计：知识库总量、文档库数、版本数、已索引页面数。"""
    try:
        libraries = await docs_mcp_client.list_libraries()
        total_chunks = 0
        total_pages = 0
        version_count = 0
        for lib in libraries:
            for ver in lib.get("versions", []):
                version_count += 1
                counts = ver.get("counts", {})
                total_chunks += counts.get("documents", 0)
                total_pages += counts.get("uniqueUrls", 0)
        return {
            "code": 200,
            "message": "ok",
            "data": {
                "totalChunks": total_chunks,
                "libraryCount": len(libraries),
                "versionCount": version_count,
                "totalPages": total_pages,
            },
        }
    except DocsMcpError:
        return {
            "code": 200,
            "message": "ok",
            "data": {
                "totalChunks": 0,
                "libraryCount": 0,
                "versionCount": 0,
                "totalPages": 0,
            },
        }


@router.get("/jobs", summary="获取任务队列")
async def get_jobs(
    status: str | None = Query(None),
    _: dict = Depends(get_current_user),
):
    try:
        result = await docs_mcp_client.get_jobs(status=status)
        jobs = result.get("jobs", []) if isinstance(result, dict) else []
        return {"code": 200, "message": "ok", "data": jobs}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": []}


@router.post("/jobs", summary="创建爬取任务")
async def create_job(body: dict, _: dict = Depends(get_current_user)):
    try:
        logger.info("create_job received body: %s", body)

        url = body.get("url", "").strip()
        library = body.get("library", "").strip()
        version = body.get("version", "").strip() or None

        if not url:
            return {"code": 400, "message": "url 不能为空", "data": None}
        if not library:
            return {"code": 400, "message": "library 不能为空", "data": None}

        additional_options = body.get("options") or {}
        if not isinstance(additional_options, dict):
            additional_options = {}

        scraper_options = {
            "url": url,
            "library": library,
            "version": version or "",
            **additional_options,
        }

        logger.info("create_job: library=%s, version=%s", library, version)

        result = await docs_mcp_client.enqueue_scrape_job(
            library=library,
            version=version,
            options=scraper_options,
        )
        return {"code": 200, "message": "任务创建成功", "data": result}
    except DocsMcpError as e:
        logger.error("DocsMcpError in create_job: %s", str(e))
        return {"code": 500, "message": str(e), "data": None}
    except Exception as e:
        logger.error("Unexpected error in create_job: %s", str(e), exc_info=True)
        return {"code": 500, "message": f"创建任务失败: {str(e)}", "data": None}


@router.post("/jobs/clear-completed", summary="清理已完成任务")
async def clear_completed(_: dict = Depends(get_current_user)):
    try:
        result = await docs_mcp_client.clear_completed_jobs()
        return {"code": 200, "message": "清理成功", "data": result}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.post("/jobs/{job_id}/cancel", summary="取消任务")
async def cancel_job(job_id: str, _: dict = Depends(get_current_user)):
    try:
        await docs_mcp_client.cancel_job(job_id)
        return {"code": 200, "message": "任务已取消", "data": None}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.get("/jobs/{job_id}", summary="获取任务详情")
async def get_job_detail(job_id: str, _: dict = Depends(get_current_user)):
    try:
        result = await docs_mcp_client.get_job_detail(job_id)
        return {"code": 200, "message": "ok", "data": result}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.post("/jobs/{job_id}/refresh", summary="刷新版本")
async def refresh_version(
    job_id: str,
    body: dict | None = None,
    _: dict = Depends(get_current_user),
):
    """根据 job 信息刷新对应版本的文档。body 需包含 library 和 version。"""
    try:
        if not body:
            return {"code": 400, "message": "请求体不能为空", "data": None}

        library = body.get("library", "").strip()
        version = body.get("version", "").strip() or None

        if not library:
            return {"code": 400, "message": "library 不能为空", "data": None}

        refresh_options = body.get("options", {})

        result = await docs_mcp_client.enqueue_refresh_job(
            library=library,
            version=version,
            options=refresh_options,
        )
        return {"code": 200, "message": "刷新任务已创建", "data": result}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.get("/libraries", summary="获取文档库列表")
async def list_libraries(_: dict = Depends(get_current_user)):
    try:
        libraries = await docs_mcp_client.list_libraries()
        return {"code": 200, "message": "ok", "data": libraries}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": []}


@router.get("/libraries/{library_name}", summary="获取文档库详情")
async def get_library_detail(library_name: str, _: dict = Depends(get_current_user)):
    try:
        libraries = await docs_mcp_client.list_libraries()
        for lib in libraries:
            if lib.get("library") == library_name:
                return {"code": 200, "message": "ok", "data": lib}
        return {"code": 404, "message": "文档库不存在", "data": None}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.get("/libraries/{library_name}/search", summary="搜索文档")
async def search_library(
    library_name: str,
    query: str = Query(...),
    version: str | None = Query(None),
    limit: int = Query(10),
    _: dict = Depends(get_current_user),
):
    try:
        results = await docs_mcp_client.search(
            library=library_name,
            query=query,
            version=version,
            limit=limit,
        )
        return {"code": 200, "message": "ok", "data": results}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": []}


@router.delete("/libraries/{library_name}/versions/{version}", summary="删除版本")
async def delete_version(
    library_name: str,
    version: str,
    _: dict = Depends(get_current_user),
):
    try:
        await docs_mcp_client.remove_version(library_name, version)
        return {"code": 200, "message": "版本已删除", "data": None}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.delete(
    "/libraries/{library_name}/versions/{version}/documents",
    summary="删除版本所有文档",
)
async def delete_version_documents(
    library_name: str,
    version: str,
    _: dict = Depends(get_current_user),
):
    """删除版本下所有文档，保留版本记录本身。适用于清除后重新抓取。"""
    try:
        await docs_mcp_client.remove_version_documents(library_name, version)
        return {"code": 200, "message": "文档已清除", "data": None}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.get("/libraries/{library_name}/exists", summary="检查文档库是否存在")
async def check_library_exists(library_name: str, _: dict = Depends(get_current_user)):
    try:
        exists = await docs_mcp_client.library_exists(library_name)
        return {"code": 200, "message": "ok", "data": {"exists": exists}}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.get("/versions", summary="获取版本列表")
async def list_versions(
    status: str | None = Query(None),
    _: dict = Depends(get_current_user),
):
    try:
        versions = await docs_mcp_client.list_versions(status=status)
        return {"code": 200, "message": "ok", "data": versions}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": []}


@router.get("/versions/by-url", summary="根据 URL 查找版本")
async def find_versions_by_url(
    url: str = Query(...),
    _: dict = Depends(get_current_user),
):
    try:
        versions = await docs_mcp_client.find_versions_by_url(url)
        return {"code": 200, "message": "ok", "data": versions}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": []}


@router.get("/versions/{version_id}/options", summary="获取版本抓取配置")
async def get_version_options(
    version_id: int,
    _: dict = Depends(get_current_user),
):
    try:
        options = await docs_mcp_client.get_version_options(version_id)
        return {"code": 200, "message": "ok", "data": options}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.put("/versions/{version_id}/options", summary="更新版本抓取配置")
async def update_version_options(
    version_id: int,
    body: dict,
    _: dict = Depends(get_current_user),
):
    try:
        await docs_mcp_client.update_version_options(version_id, body)
        return {"code": 200, "message": "配置已更新", "data": None}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.get("/events", summary="SSE 实时事件代理")
async def events_stream():
    """SSE 事件流纯转发（无需认证，EventSource 无法携带 Authorization）。

    落库由后台订阅器（services/docs_mcp_event_subscriber.py）负责，本端点仅向前端透传进度。
    """
    upstream_url = f"{settings.docs_mcp_server_url}/api/events"

    async def generate():
        try:
            timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout, proxy=None) as client:
                async with client.stream("GET", upstream_url) as resp:
                    if resp.status_code >= 400:
                        logger.error(
                            "docs-mcp SSE upstream failed: %d", resp.status_code
                        )
                        msg = f"upstream {resp.status_code}"
                        yield f'event: error\ndata: {{"message": "{msg}"}}\n\n'
                        return
                    async for line in resp.aiter_lines():
                        yield line + "\n"
        except httpx.HTTPError as e:
            logger.error("docs-mcp SSE connection error: %s", str(e))
            yield f'event: error\ndata: {{"message": "{str(e)}"}}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/fetch-url", summary="抓取 URL 转 Markdown")
async def fetch_url(body: dict, _: dict = Depends(get_current_user)):
    """调用 docs-mcp-server 的 fetch_url 工具，抓取单个 URL 并转换为 Markdown。"""
    try:
        url = body.get("url", "").strip()
        if not url:
            return {"code": 400, "message": "url 不能为空", "data": None}

        follow_redirects = body.get("followRedirects", True)
        scrape_mode = body.get("scrapeMode")
        headers = body.get("headers")

        result = await docs_mcp_client.fetch_url(
            url=url,
            follow_redirects=follow_redirects,
            scrape_mode=scrape_mode,
            headers=headers,
        )
        return {"code": 200, "message": "ok", "data": result}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


@router.post("/upload", summary="上传文档")
async def upload_document(
    library: str = Form(...),
    version: str = Form(""),
    auto_ingest: bool = Form(True),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """上传本地文档，提取内容。auto_ingest=true 时自动入库，false 时仅提取。"""
    if not library.strip():
        return {"code": 400, "message": "library 不能为空", "data": None}
    if not file.filename:
        return {"code": 400, "message": "文件名不能为空", "data": None}

    try:
        file_bytes = await file.read()
    except Exception as e:
        return {"code": 400, "message": f"读取文件失败: {str(e)}", "data": None}

    if len(file_bytes) == 0:
        return {"code": 400, "message": "文件内容为空", "data": None}

    import os

    _, ext = os.path.splitext(file.filename.lower())
    from services.doc_upload_service import ALL_SUPPORTED_EXTENSIONS

    if ext not in ALL_SUPPORTED_EXTENSIONS:
        return {"code": 400, "message": f"不支持的文件格式: {ext}", "data": None}

    created_by = current_user.get("id") if isinstance(current_user, dict) else None
    async with async_session() as session:
        record = await doc_upload_service.upload_document(
            session=session,
            file_bytes=file_bytes,
            file_name=file.filename,
            library=library.strip(),
            version=version.strip() or None,
            created_by=created_by,
            auto_ingest=auto_ingest,
        )
        await session.commit()

    if record["status"] == "failed":
        return {
            "code": 500,
            "message": f"文档处理失败: {record['error_message']}",
            "data": record,
        }

    msg = "文档入库成功" if auto_ingest else "文档提取成功"
    return {"code": 200, "message": msg, "data": record}


@router.post("/uploads/{record_id}/ingest", summary="上传文档入库")
async def ingest_upload(
    record_id: int,
    current_user: dict = Depends(get_current_user),
):
    """异步派发上传文档入库任务到 Celery，立即返回。"""
    from tasks.doc_tasks import ingest_upload_task

    ingest_upload_task.delay(record_id)
    return {"code": 200, "message": "入库任务已提交", "data": None}


@router.get("/uploads", summary="查询文档上传记录")
async def list_uploads(
    library: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: dict = Depends(get_current_user),
    session=Depends(get_db),
):
    """查询文档上传记录，可按文档库筛选。"""
    result = await doc_upload_service.list_upload_records(
        session=session,
        library=library,
        page=page,
        page_size=page_size,
    )
    return {"code": 200, "message": "ok", "data": result}


@router.get("/tasks", summary="查询文档任务列表")
async def list_doc_tasks(
    source: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: dict = Depends(get_current_user),
):
    """合并查询爬取任务与上传记录，按创建时间倒序统一分页。"""
    from services import doc_task_service

    async with async_session() as session:
        result = await doc_task_service.list_tasks(
            session=session,
            source=source,
            status=status,
            page=page,
            page_size=page_size,
        )
    return {"code": 200, "message": "ok", "data": result}


@router.delete("/uploads/{record_id}", summary="删除上传记录")
async def delete_upload(
    record_id: int,
    _: dict = Depends(get_current_user),
):
    """删除一条上传记录。"""
    async with async_session() as session:
        await doc_upload_service.delete_upload(session, record_id)
        await session.commit()
    return {"code": 200, "message": "上传记录已删除", "data": None}


# ── Crawl Tasks（crawl-only 解耦模式） ──


@router.post("/crawl-tasks", summary="创建爬取任务(crawl-only)")
async def create_crawl_task(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """创建 crawl-only 任务：只爬取不入库，页面数据通过 SSE 实时推送并持久化。"""
    url = body.get("url", "").strip()
    library = body.get("library", "").strip()
    version = body.get("version", "").strip()

    if not url:
        return {"code": 400, "message": "url 不能为空", "data": None}
    if not library:
        return {"code": 400, "message": "library 不能为空", "data": None}

    additional_options = body.get("options") or {}
    if not isinstance(additional_options, dict):
        additional_options = {}

    scraper_options = {
        "url": url,
        "library": library,
        "version": version or "",
        **additional_options,
    }

    created_by = current_user.get("id") if isinstance(current_user, dict) else None
    from services import crawl_task_service

    async with async_session() as session:
        try:
            result = await crawl_task_service.create_crawl_task(
                session=session,
                url=url,
                library=library,
                version=version or None,
                scraper_options=scraper_options,
                created_by=created_by,
                auto_ingest=body.get("auto_ingest", False),
            )
            await session.commit()
            return {"code": 200, "message": "爬取任务创建成功", "data": result}
        except ValueError as e:
            return {"code": 400, "message": str(e), "data": None}


@router.get("/crawl-tasks", summary="获取爬取任务列表")
async def list_crawl_tasks(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: dict = Depends(get_current_user),
):
    """分页查询 crawl-only 任务。"""
    from services import crawl_task_service

    async with async_session() as session:
        result = await crawl_task_service.list_crawl_tasks(
            session=session,
            status=status,
            page=page,
            page_size=page_size,
        )
    return {"code": 200, "message": "ok", "data": result}


@router.get("/crawl-tasks/{task_id}", summary="获取爬取任务详情")
async def get_crawl_task(
    task_id: int,
    _: dict = Depends(get_current_user),
):
    """获取单个 crawl-only 任务详情。"""
    from services import crawl_task_service

    async with async_session() as session:
        result = await crawl_task_service.get_crawl_task(session, task_id)
    if result is None:
        return {"code": 404, "message": "爬取任务不存在", "data": None}
    return {"code": 200, "message": "ok", "data": result}


@router.get("/crawl-tasks/{task_id}/pages", summary="获取爬取页面列表")
async def list_crawl_pages(
    task_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: dict = Depends(get_current_user),
):
    """分页查询 crawl task 下的页面。"""
    from services import crawl_task_service

    async with async_session() as session:
        result = await crawl_task_service.list_crawl_pages(
            session=session,
            task_id=task_id,
            page=page,
            page_size=page_size,
        )
    return {"code": 200, "message": "ok", "data": result}


@router.post("/crawl-tasks/{task_id}/ingest", summary="入库所有爬取页面")
async def ingest_crawl_task(
    task_id: int,
    _: dict = Depends(get_current_user),
):
    """异步派发 crawl task 入库任务到 Celery，立即返回。"""
    from services import crawl_task_service
    from tasks.doc_tasks import ingest_crawl_task as ingest_crawl_task_celery

    async with async_session() as session:
        task = await crawl_task_service.get_crawl_task(session, task_id)
    if task is None:
        return {"code": 404, "message": "爬取任务不存在", "data": None}
    ingest_crawl_task_celery.delay(task_id)
    return {"code": 200, "message": "入库任务已提交", "data": task}


@router.delete("/crawl-tasks/{task_id}", summary="删除爬取任务")
async def delete_crawl_task(
    task_id: int,
    _: dict = Depends(get_current_user),
):
    """删除 crawl task 及其所有页面数据。"""
    from services import crawl_task_service

    async with async_session() as session:
        await crawl_task_service.delete_crawl_task(session, task_id)
        await session.commit()
    return {"code": 200, "message": "爬取任务已删除", "data": None}
