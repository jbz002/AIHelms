"""文档知识库与文档 CRUD 端点。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from exceptions import ConflictError, NotFoundError, ValidationError
from repositories import document_library_repo
from services import (
    document_api_batch_service,
    document_api_classify_service,
    document_api_service,
    document_library_service,
    document_proxy_service,
    document_service,
)

router = APIRouter(tags=["AI实验室"])

# ── 知识库请求模型 ──


class CreateLibraryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="知识库名称")
    description: str = Field(default="", max_length=500, description="知识库描述")


class UpdateLibraryRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)


# ── 文档请求模型 ──


class UpdateDocumentRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    content: str | None = None
    metadata_: dict | None = Field(default=None, description="文档元数据")


class ProxyRequestRequest(BaseModel):
    method: str = Field(..., max_length=10, description="HTTP 方法")
    url: str = Field(..., max_length=2000, description="目标 URL")
    headers: dict[str, str] = Field(default_factory=dict, description="自定义请求头")
    body: str | None = Field(default=None, description="请求体原文")


async def _assert_library_owned(
    session: AsyncSession, library_id: int, current_user: dict
) -> None:
    """校验知识库归属：admin 放行；非 owner 返 403，不存在返 404。"""
    if current_user.get("is_admin"):
        return
    try:
        lib = await document_library_service.get_library_by_id(session, library_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if lib["created_by"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="无权操作他人的知识库")


async def _assert_library_name_owned(
    session: AsyncSession, library_name: str, current_user: dict
) -> None:
    """按库名校验归属：库不存在放行（交下游报错）；admin 放行；非 owner 返 403。"""
    if current_user.get("is_admin"):
        return
    existing = await document_library_repo.find_by_name(session, library_name)
    if existing is not None and existing.created_by != current_user["id"]:
        raise HTTPException(status_code=403, detail="无权操作他人的知识库")


async def _assert_document_owned(
    session: AsyncSession, document_id: int, current_user: dict
) -> None:
    """校验文档归属：admin 放行；非 owner 返 403，不存在返 404。"""
    if current_user.get("is_admin"):
        return
    try:
        doc = await document_service.get_document_by_id(session, document_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc["created_by"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="无权操作他人的文档")


# ── 知识库 CRUD ──


library_router = APIRouter(prefix="/document-libraries", tags=["AI实验室"])


@library_router.post("", summary="创建知识库")
async def create_library(
    req: CreateLibraryRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("document_library:create")),
):
    try:
        result = await document_library_service.create_library(
            session,
            name=req.name,
            description=req.description,
            created_by=current_user["id"],
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"code": 200, "message": "知识库创建成功", "data": result}


@library_router.get("")
async def list_libraries(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query("", max_length=200),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document_library:read")),
):
    if keyword:
        result = await document_library_service.search_libraries(
            session, keyword, page, page_size
        )
    else:
        items = await document_library_service.list_libraries(session)
        total = len(items)
        start = (page - 1) * page_size
        items = items[start : start + page_size]
        result = {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    return {"code": 200, "message": "ok", "data": result}


@library_router.get("/{library_id}")
async def get_library(
    library_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document_library:read")),
):
    try:
        result = await document_library_service.get_library_by_id(session, library_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"code": 200, "message": "ok", "data": result}


@library_router.put("/{library_id}", summary="更新知识库")
async def update_library(
    library_id: int,
    req: UpdateLibraryRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("document_library:update")),
):
    await _assert_library_owned(session, library_id, current_user)
    try:
        result = await document_library_service.update_library(
            session, library_id, name=req.name, description=req.description
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="知识库不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"code": 200, "message": "知识库更新成功", "data": result}


@library_router.delete("/{library_id}", summary="删除知识库")
async def delete_library(
    library_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("document_library:delete")),
):
    await _assert_library_owned(session, library_id, current_user)
    try:
        await document_library_service.delete_library(session, library_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"code": 200, "message": "知识库删除成功", "data": None}


# ── 库级接口提取与分类 ──


@library_router.post("/{library_name}/extract-interfaces", summary="批量提取库接口")
async def extract_library_interfaces(
    library_name: str,
    force: bool = False,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("document:batch_extract")),
):
    """批量提取库内所有已入库文档的 API 接口，异步任务。force=true 时忽略增量跳过，全量重新提取。"""
    await _assert_library_name_owned(session, library_name, current_user)
    try:
        result = await document_api_batch_service.create_library_extraction(
            session, library_name, current_user, force=force
        )
    except ConflictError:
        raise HTTPException(status_code=409, detail="该库已有批量提取任务在进行中")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "code": 200,
        "message": "批量提取任务已提交（强制全量）" if force else "批量提取任务已提交",
        "data": result,
    }


@library_router.get("/{library_name}/extract-status")
async def get_library_extract_status(
    library_name: str,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    """返回库最近一次批量提取任务状态（前端轮询用）。"""
    result = await document_api_batch_service.get_library_extraction_status(
        session, library_name
    )
    return {"code": 200, "message": "ok", "data": result}


@library_router.get("/{library_name}/extract-preview")
async def get_library_extract_preview(
    library_name: str,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    """预览库级提取：将提取（新增/变更）与将跳过（未变更）的文档分组，前端确认弹窗用。"""
    result = await document_api_batch_service.preview_library_extraction(
        session, library_name
    )
    return {"code": 200, "message": "ok", "data": result}


@library_router.post("/{library_name}/classify-interfaces", summary="分类库接口")
async def classify_library_interfaces(
    library_name: str,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("document:classify")),
):
    """AI 按业务模块对库内接口统一分类，异步任务。"""
    try:
        result = await document_api_classify_service.create_classification(
            session, library_name, current_user
        )
    except ConflictError:
        raise HTTPException(status_code=409, detail="该库已有分类任务在进行中")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "分类任务已提交", "data": result}


@library_router.get("/{library_name}/classify-status")
async def get_library_classify_status(
    library_name: str,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    """返回库最近一次分类任务状态（前端轮询用）。"""
    result = await document_api_classify_service.get_classification_status(
        session, library_name
    )
    return {"code": 200, "message": "ok", "data": result}


@library_router.get("/{library_name}/interfaces")
async def get_library_interfaces(
    library_name: str,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    """返回库级全部接口（跨文档，扁平 + category + operation 内联）。"""
    result = await document_api_classify_service.build_library_endpoints(
        session, library_name
    )
    return {"code": 200, "message": "ok", "data": result}


# ── 文档 CRUD（无 POST，文档由 upload/crawl 自动创建） ──

document_router = APIRouter(prefix="/documents", tags=["AI实验室"])


class IngestBatchRequest(BaseModel):
    library: str | None = Field(default=None, max_length=200)
    source_type: str | None = Field(default=None, max_length=20)


@document_router.get("")
async def list_documents(
    library: str | None = Query(None, max_length=200),
    source_type: str | None = Query(None, max_length=20),
    ingest_status: str | None = Query(None, max_length=20),
    version: str | None = Query(None, max_length=200),
    title: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    result = await document_service.list_documents(
        session,
        library=library,
        source_type=source_type,
        ingest_status=ingest_status,
        version=version,
        title=title,
        page=page,
        page_size=page_size,
    )
    return {"code": 200, "message": "ok", "data": result}


@document_router.get("/stats")
async def get_ingest_stats(
    library: str | None = Query(None, max_length=200),
    version: str | None = Query(None, max_length=200),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    result = await document_service.get_ingest_stats(
        session, library=library, version=version
    )
    return {"code": 200, "message": "ok", "data": result}


@document_router.get("/dashboard-summary")
async def get_dashboard_summary(
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    result = await document_service.get_dashboard_summary(session)
    return {"code": 200, "message": "ok", "data": result}


@document_router.post("/ingest-batch", summary="批量入库文档")
async def ingest_batch(
    req: IngestBatchRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:update")),
):
    from tasks.doc_tasks import ingest_batch_task

    task = ingest_batch_task.delay(library=req.library, source_type=req.source_type)
    return {"code": 200, "message": "批量入库任务已提交", "data": {"task_id": task.id}}


@document_router.get("/{document_id}")
async def get_document(
    document_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    try:
        result = await document_service.get_document_by_id(session, document_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"code": 200, "message": "ok", "data": result}


@document_router.get("/{document_id}/spec")
async def get_document_spec(
    document_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    """返回文档的 OpenAPI spec，供前端 Scalar 渲染接口调试页。"""
    try:
        result = await document_api_service.build_openapi_spec(session, document_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"code": 200, "message": "ok", "data": result}


@document_router.get("/{document_id}/extract-status")
async def get_extract_status(
    document_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    """返回文档最近一次接口提取任务状态（前端轮询用）。"""
    result = await document_api_service.get_extract_status(session, document_id)
    return {"code": 200, "message": "ok", "data": result}


@document_router.post("/{document_id}/proxy", summary="调试代理请求")
async def proxy_document_request(
    document_id: int,
    req: ProxyRequestRequest,
    _: dict = Depends(require_permission("document:read")),
):
    """接口调试器 Try-it-out：后端转发请求以规避浏览器 CORS。"""
    try:
        result = await document_proxy_service.proxy_request(
            method=req.method,
            url=req.url,
            headers=req.headers,
            body=req.body,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "代理请求完成", "data": result}


@document_router.post("/{document_id}/extract-interfaces", summary="提取文档接口")
async def extract_interfaces(
    document_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("document:extract")),
):
    """AI 提取文档中的 API 接口，异步任务。"""
    await _assert_document_owned(session, document_id, current_user)
    try:
        result = await document_api_service.create_extraction(
            session, document_id, current_user
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在")
    except ConflictError:
        raise HTTPException(status_code=409, detail="该文档已有接口提取任务在进行中")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "接口提取任务已提交", "data": result}


@document_router.put("/{document_id}", summary="更新文档")
async def update_document(
    document_id: int,
    req: UpdateDocumentRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("document:update")),
):
    await _assert_document_owned(session, document_id, current_user)
    try:
        result = await document_service.update_document(
            session,
            document_id,
            title=req.title,
            content=req.content,
            metadata_=req.metadata_,
            current_user=current_user,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"code": 200, "message": "文档更新成功", "data": result}


@document_router.delete("/{document_id}", summary="删除文档")
async def delete_document(
    document_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("document:delete")),
):
    await _assert_document_owned(session, document_id, current_user)
    try:
        await document_service.delete_document(session, document_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"code": 200, "message": "文档删除成功", "data": None}


@document_router.post("/{document_id}/ingest", summary="入库文档")
async def ingest_document(
    document_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:update")),
):
    from tasks.doc_tasks import ingest_document_task

    task = ingest_document_task.delay(document_id)
    return {"code": 200, "message": "入库任务已提交", "data": {"task_id": task.id}}
