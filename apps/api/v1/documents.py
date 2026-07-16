"""文档知识库与文档 CRUD 端点。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from exceptions import ConflictError, NotFoundError
from services import document_library_service, document_service

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
    _: dict = Depends(require_permission("document_library:update")),
):
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
    _: dict = Depends(require_permission("document_library:delete")),
):
    try:
        await document_library_service.delete_library(session, library_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"code": 200, "message": "知识库删除成功", "data": None}


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
        page=page,
        page_size=page_size,
    )
    return {"code": 200, "message": "ok", "data": result}


@document_router.get("/stats")
async def get_ingest_stats(
    library: str | None = Query(None, max_length=200),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:read")),
):
    result = await document_service.get_ingest_stats(session, library=library)
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


@document_router.put("/{document_id}", summary="更新文档")
async def update_document(
    document_id: int,
    req: UpdateDocumentRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:update")),
):
    try:
        result = await document_service.update_document(
            session,
            document_id,
            title=req.title,
            content=req.content,
            metadata_=req.metadata_,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"code": 200, "message": "文档更新成功", "data": result}


@document_router.delete("/{document_id}", summary="删除文档")
async def delete_document(
    document_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("document:delete")),
):
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
