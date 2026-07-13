"""API文档管理 — docs-mcp-server 反向代理路由。"""

import logging

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from core.config import settings
from core.deps import get_current_user
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
        result = await docs_mcp_client.enqueue_scrape_job(
            library=body["library"],
            version=body.get("version"),
            options=body.get("options", {}),
        )
        return {"code": 200, "message": "任务创建成功", "data": result}
    except DocsMcpError as e:
        return {"code": 500, "message": str(e), "data": None}


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


@router.post("/jobs/{job_id}/refresh", summary="刷新版本")
async def refresh_version(
    job_id: str,
    body: dict | None = None,
    _: dict = Depends(get_current_user),
):
    """根据 job 信息刷新对应版本的文档。body 需包含 library 和 version。"""
    try:
        library = body.get("library", "") if body else ""
        version = body.get("version") if body else None
        options = body.get("options") if body else None
        result = await docs_mcp_client.enqueue_refresh_job(
            library=library,
            version=version,
            options=options,
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


@router.get("/events", summary="SSE 实时事件代理")
async def events_stream():
    """SSE 事件流代理（无需认证，EventSource 无法携带 Authorization）。"""

    async def generate():
        web_url = settings.docs_mcp_server_web_url
        upstream_url = f"{web_url}/web/events"
        try:
            async with httpx.AsyncClient(timeout=60.0, proxy=None) as client:
                async with client.stream("GET", upstream_url) as resp:
                    if resp.status_code >= 400:
                        logger.error(
                            "docs-mcp SSE upstream failed: %d",
                            resp.status_code,
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
