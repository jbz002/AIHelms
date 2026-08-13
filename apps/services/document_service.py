"""文档查询/更新/删除服务。文档创建由 upload/crawl 流程自动完成。"""

import hashlib
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from models.db import Document
from repositories import (
    crawled_page_repo,
    doc_upload_repo,
    document_api_repo,
    document_repo,
)
from services import document_library_service
from services.docs_mcp_client import DocsMcpError, docs_mcp_client

logger = logging.getLogger(__name__)


async def _sync_source_status(
    session: AsyncSession, doc: Document, chunk_count: int
) -> None:
    """单文档入库成功后按来源同步源表状态。

    避免文档列表的「单条入库」与任务列表的「批量入库」两套入口真相漂移
    （否则 crawl 页 crawled_pages.ingest_status 留 pending，批量重试会重复向量化）。
    """
    if doc.source_type == "crawl" and doc.source_id:
        await crawled_page_repo.mark_ingested(session, [doc.source_id])
    elif doc.source_type == "upload" and doc.source_id:
        await doc_upload_repo.update_status(
            session, doc.source_id, "completed", chunk_count=chunk_count
        )


def build_ingest_url(
    source_type: str,
    source_id: int | None,
    metadata: dict | None,
    doc_id: int | None = None,
) -> str:
    """计算文档入库提交给 docs-mcp 的 url（定位 page 的唯一钥匙，必填）。

    upload: local://uploads/{source_id}/{file_name} — 带 record_id 避免同名碰撞。
    crawl: metadata.url（每页唯一）。
    兜底: aihelms://document/{doc_id}；无 doc_id 退化到 source 维度。
    """
    meta = metadata or {}
    if source_type == "crawl" and meta.get("url"):
        return str(meta["url"])
    if source_type == "upload" and source_id and meta.get("file_name"):
        return f"local://uploads/{source_id}/{meta['file_name']}"
    if doc_id is not None:
        return f"aihelms://document/{doc_id}"
    if source_id is not None:
        return f"aihelms://{source_type}/{source_id}"
    return "aihelms://document/unknown"


def _resolve_ingest_url(doc: Document) -> str:
    """入库时取 url：优先读 ingest_url 列（终身稳定），空则回退推导。

    reingest 读列保证覆盖 docs-mcp 同一 page（url 不漂移），不产生孤儿向量。
    """
    if doc.ingest_url:
        return doc.ingest_url
    return build_ingest_url(doc.source_type, doc.source_id, doc.metadata_, doc.id)


def _serialize_document(doc: Document) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "content": doc.content[:500] if doc.content else "",
        "library": doc.library,
        "version": doc.version,
        "source_type": doc.source_type,
        "source_id": doc.source_id,
        "chunk_count": doc.chunk_count,
        "ingest_status": doc.ingest_status,
        "content_hash": doc.content_hash,
        "error_message": doc.error_message,
        "created_by": doc.created_by,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "metadata": doc.metadata_ if doc.metadata_ else {},
    }


async def _resolve_latest_version(library: str) -> str | None:
    """把 "latest" 解析为当时最新版本（持续锁定）。

    复用 docs_mcp_client.resolve_version：bestMatch 非空→最高 semver；
    bestMatch=null 且 hasUnversioned→""（落 unversioned，与 search 一致）；
    库空/解析失败→None（不按版本过滤，保底）。
    """
    return await docs_mcp_client.resolve_version(library, "latest")


async def _normalize_version_filter(
    library: str | None, version: str | None
) -> str | None:
    """version="latest" 时解析为具体版本号；其余原样返回。library 为空时无法解析。"""
    if version and version.lower() == "latest" and library:
        return await _resolve_latest_version(library)
    return version


async def get_document_by_id(session: AsyncSession, document_id: int) -> dict:
    """根据 ID 获取文档详情。"""
    doc = await document_repo.find_by_id(session, document_id)
    if doc is None:
        raise NotFoundError("document", document_id)
    result = _serialize_document(doc)
    result["content"] = doc.content or ""
    return result


async def list_documents(
    session: AsyncSession,
    library: str | None = None,
    source_type: str | None = None,
    ingest_status: str | None = None,
    version: str | None = None,
    title: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询文档列表，支持多条件过滤和分页。"""
    if library and not version:
        version = await _resolve_latest_version(library)
    version = await _normalize_version_filter(library, version)
    total = await document_repo.count_all(
        session, library, source_type, ingest_status, version, title
    )
    docs = await document_repo.list_all(
        session,
        library,
        source_type,
        ingest_status,
        version,
        title,
        page,
        page_size,
    )
    return {
        "items": [_serialize_document(d) for d in docs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def update_document(
    session: AsyncSession,
    document_id: int,
    title: str | None = None,
    content: str | None = None,
    metadata_: dict | None = None,
    current_user: dict | None = None,
) -> dict:
    """更新文档标题/内容/元数据。内容变更时重置入库状态并按需重提接口。"""
    doc = await document_repo.find_by_id(session, document_id)
    if doc is None:
        raise NotFoundError("document", document_id)
    await document_repo.update_document_fields(
        session, document_id, title=title, content=content, metadata_=metadata_
    )
    content_changed = False
    if content is not None:
        new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if new_hash != doc.content_hash:
            await document_repo.update_content_hash(session, document_id, new_hash)
            await document_repo.update_ingest_status(session, document_id, "pending")
            content_changed = True
    await session.commit()
    await session.refresh(doc)

    # 内容变更且文档已有接口 → 后端直接派发提取，不依赖前端轮询或入库结果
    # （提取只读平台 DB content，与 docs-mcp 向量化无关）。无历史接口的新文档
    # 不触发，符合"新增不自动提取"的省 token 设计。
    if content_changed and current_user is not None:
        await _maybe_reextract_interfaces(session, doc, current_user)

    return _serialize_document(doc)


async def _maybe_reextract_interfaces(
    session: AsyncSession, doc: Document, current_user: dict
) -> None:
    """文档已有历史接口时派发一次提取；失败不影响编辑保存。

    复用 document_api_service.create_extraction（含并发防护与 Celery 派发）。
    无历史接口的文档跳过（避免对未提取过的文档浪费 LLM 调用）。
    """
    try:
        if await document_api_repo.count_by_document(session, doc.id) <= 0:
            return
        from services import document_api_service

        await document_api_service.create_extraction(session, doc.id, current_user)
        logger.info("auto re-extract enqueued after edit: doc_id=%s", doc.id)
    except Exception:
        # 并发冲突(已有任务在跑)/派发异常均不影响编辑结果，仅记日志
        logger.warning(
            "auto re-extract interfaces skipped: doc_id=%s", doc.id, exc_info=True
        )


async def delete_document(session: AsyncSession, document_id: int) -> None:
    """删除文档。平台 DB 先删并 commit，再尽力同步 docs-mcp 删该文档向量。

    外部失败仅记日志不回滚（平台 DB 是唯一数据源），留孤儿向量由重试/对账清理。
    """
    doc = await document_repo.find_by_id(session, document_id)
    if doc is None:
        raise NotFoundError("document", document_id)
    library = doc.library
    version = doc.version or ""
    ingest_url = _resolve_ingest_url(doc)
    await document_repo.delete_document(session, document_id)
    await session.commit()
    try:
        await docs_mcp_client.remove_document(library, version, ingest_url)
    except DocsMcpError:
        logger.warning(
            "docs-mcp remove_document failed during document delete",
            extra={
                "document_id": document_id,
                "library": library,
                "version": version,
            },
        )


async def ingest_document(
    session: AsyncSession,
    document_id: int,
) -> dict:
    """单文档入库到 docs-mcp。内容未变且已入库时跳过。"""
    doc = await document_repo.find_by_id(session, document_id)
    if doc is None:
        raise NotFoundError("document", document_id)

    if not doc.content:
        await document_repo.update_ingest_status(
            session, document_id, "failed", error_message="文档内容为空"
        )
        raise ValueError("文档内容为空，无法入库")

    current_hash = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()
    if current_hash == doc.content_hash and doc.ingest_status == "ingested":
        result = {
            **_serialize_document(doc),
            "skipped": True,
            "reason": "content_unchanged",
        }
        return result

    await document_repo.update_ingest_status(session, document_id, "ingesting")

    try:
        result = await docs_mcp_client.ingest_raw(
            library=doc.library,
            version=doc.version or None,
            documents=[
                {
                    "url": _resolve_ingest_url(doc),
                    "title": doc.title or "untitled",
                    "contentType": "text/markdown",
                    "content": doc.content,
                }
            ],
        )
        # docs-mcp ingest-raw 返回 { ingested: 文档数, chunks: 块数 }；
        # chunks 才是该文档真分块数，旧版无该字段时回退 ingested
        chunk_count = (
            (result.get("chunks") or result.get("ingested") or 0)
            if isinstance(result, dict)
            else 0
        )
        await document_repo.update_ingest_status(
            session, document_id, "ingested", chunk_count=chunk_count
        )
        await document_repo.update_content_hash(session, document_id, current_hash)
        await document_library_service.refresh_document_counts(session, doc.library)
        await _sync_source_status(session, doc, chunk_count)
        await session.flush()
        await session.refresh(doc)
        return _serialize_document(doc)

    except DocsMcpError as e:
        await document_repo.update_ingest_status(
            session, document_id, "failed", error_message=str(e)[:500]
        )
        await session.flush()
        raise


async def ingest_batch(
    session: AsyncSession,
    library: str | None = None,
    source_type: str | None = None,
) -> dict:
    """批量入库 pending/failed 文档，逐个处理、失败不中断。"""
    docs = await document_repo.list_by_ingest_status(
        session,
        statuses=["pending", "failed"],
        library=library,
        source_type=source_type,
    )
    total = len(docs)
    if total == 0:
        return {"total": 0, "ingested": 0, "failed": 0, "skipped": 0}

    ingested, failed, skipped = 0, 0, 0
    for doc in docs:
        current_hash = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()
        if current_hash == doc.content_hash and doc.ingest_status == "ingested":
            skipped += 1
            continue

        try:
            await document_repo.update_ingest_status(session, doc.id, "ingesting")
            result = await docs_mcp_client.ingest_raw(
                library=doc.library,
                version=doc.version or None,
                documents=[
                    {
                        "url": _resolve_ingest_url(doc),
                        "title": doc.title or "untitled",
                        "contentType": "text/markdown",
                        "content": doc.content,
                    }
                ],
            )
            # chunks 为真分块数（ingested 是批内文档数，单文档批恒为 1）
            chunk_count = (
                (result.get("chunks") or result.get("ingested") or 0)
                if isinstance(result, dict)
                else 0
            )
            await document_repo.update_ingest_status(
                session, doc.id, "ingested", chunk_count=chunk_count
            )
            await document_repo.update_content_hash(session, doc.id, current_hash)
            await _sync_source_status(session, doc, chunk_count)
            ingested += 1
        except DocsMcpError as e:
            await document_repo.update_ingest_status(
                session, doc.id, "failed", error_message=str(e)[:500]
            )
            logger.warning("batch ingest failed for doc %s: %s", doc.id, str(e))
            failed += 1

    await document_library_service.refresh_document_counts(session, library)
    await session.flush()
    return {"total": total, "ingested": ingested, "failed": failed, "skipped": skipped}


async def get_ingest_stats(
    session: AsyncSession,
    library: str | None = None,
    version: str | None = None,
) -> dict:
    """获取文档入库统计。"""
    if library and not version:
        version = await _resolve_latest_version(library)
    version = await _normalize_version_filter(library, version)
    rows = await document_repo.count_grouped_by_status(session, library, version)
    by_status = {r["ingest_status"]: r["count"] for r in rows}
    total_documents = sum(r["count"] for r in rows)
    total_chunks = sum(r["total_chunks"] for r in rows)
    return {
        "by_status": by_status,
        "total_documents": total_documents,
        "total_chunks": total_chunks,
        "library": library,
    }


async def get_dashboard_summary(session: AsyncSession) -> dict:
    """仪表盘汇总：全局来源/文档数 + 按 library 细分。

    一次 SQL 拿 (library, source_type, ingest_status, count) 行，本地累加成
    global 与 by_library 两份视图。library 键全部小写，对齐 document_repo 的
    func.lower 归一化，供前端按 docs-mcp 库名小写后查表筛选。
    """
    rows = await document_repo.count_grouped_by_library_source_status(session)

    global_by_source: dict[str, int] = {}
    global_total = 0
    by_library: dict[str, dict] = {}

    for row in rows:
        lib, src, status = row["library"], row["source_type"], row["ingest_status"]
        count = int(row["count"])

        global_by_source[src] = global_by_source.get(src, 0) + count
        global_total += count

        bucket = by_library.setdefault(
            lib, {"by_source": {}, "by_status": {}, "total_documents": 0}
        )
        bucket["by_source"][src] = bucket["by_source"].get(src, 0) + count
        bucket["by_status"][status] = bucket["by_status"].get(status, 0) + count
        bucket["total_documents"] += count

    return {
        "global": {
            "by_source": global_by_source,
            "total_documents": global_total,
        },
        "by_library": by_library,
    }
