"""库级批量接口提取服务。

顺序处理库内每个 ingested 文档，复用单文档提取逻辑
（document_api_service.process_extraction），聚合计数进度。
Celery worker 调 process_library_extraction。

LLM 调用走平台 key（services/platform_llm.py，复用 LITELLM_MASTER_KEY）。
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_worker_session_factory
from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import DocumentApiBatchJob, DocumentApiSpec
from repositories import document_api_repo, document_repo
from services import document_api_service, platform_llm, platform_settings_service

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _progress(value: int, completed: int, step: str) -> dict:
    return {"value": value, "completed": completed, "total": 4, "step": step}


def _should_skip_incremental(
    doc_content_hash: str,
    existing_count: int,
    latest_spec: DocumentApiSpec | None,
) -> bool:
    """已成功提取且文档内容未变更 → 增量跳过。

    任一前提不成立（无 hash / 无既有接口 / 无成功任务 / hash 变更）则需（重）提取。
    """
    if not doc_content_hash or existing_count <= 0 or latest_spec is None:
        return False
    return (latest_spec.content_hash or "") == doc_content_hash


def _serialize_batch_job(job: DocumentApiBatchJob) -> dict:
    return {
        "id": job.id,
        "job_id": job.job_id,
        "library": job.library,
        "status": job.status,
        "model_id": job.model_id,
        "model_name": job.model_name,
        "total_documents": job.total_documents,
        "completed_documents": job.completed_documents,
        "failed_documents": job.failed_documents,
        "skipped_documents": job.skipped_documents,
        "total_endpoints": job.total_endpoints,
        "summary": job.summary or {},
        "error_message": job.error_message,
        "created_by": job.created_by,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


# ── 创建任务 ──────────────────────────────────────────────────────────────────


async def create_library_extraction(
    session: AsyncSession, library_name: str, current_user: dict, force: bool = False
) -> dict:
    docs = await document_repo.list_by_ingest_status(
        session, ["ingested"], library=library_name
    )
    if not docs:
        raise ValidationError("该库无已入库文档，无法批量提取")
    if await document_api_repo.find_active_batch_by_library(session, library_name):
        raise ConflictError("该库已有批量提取任务在进行中")

    job = DocumentApiBatchJob(
        job_id=f"DAB-{uuid4().hex[:12]}",
        library=library_name,
        status="queued",
        total_documents=len(docs),
        created_by=int(current_user["id"]),
        summary={"progress": _progress(0, 0, "排队中"), "force": force},
    )
    job = await document_api_repo.create_batch_job(session, job)
    await session.commit()
    await session.refresh(job)

    from tasks.document_api_tasks import extract_library_interfaces_task

    extract_library_interfaces_task.delay(job.id)
    return _serialize_batch_job(job)


# ── worker 体 ─────────────────────────────────────────────────────────────────


async def process_library_extraction(session: AsyncSession, job_pk: int) -> dict:
    job = await document_api_repo.find_batch_by_id(session, job_pk)
    if job is None or job.status not in ("queued", "running"):
        return {}
    force = bool((job.summary or {}).get("force"))

    job.status = "running"
    job.started_at = _now()
    job.summary = {**job.summary, "progress": _progress(10, 1, "初始化")}
    await session.commit()

    try:
        if not platform_llm.get_platform_api_key():
            await _fail_job(session, job, "平台未配置 LLM 主密钥(LITELLM_MASTER_KEY)")
            return _serialize_batch_job(job)
        resolved = await platform_settings_service.resolve_default_model(session)
        if resolved is None:
            await _fail_job(session, job, "平台未配置默认模型，请在平台设置中配置")
            return _serialize_batch_job(job)
        job.model_id, job.model_name = resolved

        docs = await document_repo.list_by_ingest_status(
            session, ["ingested"], library=job.library
        )
        total = len(docs)
        job.total_documents = total
        job.summary = {**job.summary, "progress": _progress(20, 2, "批量提取中")}
        await session.commit()

        for index, doc in enumerate(docs, start=1):
            progress_value = 20 + int(70 * index / max(total, 1))
            if not (doc.content or "").strip():
                job.failed_documents += 1
                job.summary = {
                    **job.summary,
                    "progress": _progress(
                        progress_value, 3, f"跳过空文档 {index}/{total}"
                    ),
                }
                await session.commit()
                continue
            if await document_api_repo.find_active_by_document(session, doc.id):
                # 该文档已有单文档提取任务在进行中，跳过避免冲突
                continue

            if not force:
                existing = await document_api_repo.count_by_document(session, doc.id)
                latest_done = (
                    await document_api_repo.find_latest_completed_by_document(
                        session, doc.id
                    )
                    if existing > 0
                    else None
                )
                if _should_skip_incremental(doc.content_hash, existing, latest_done):
                    # 已成功提取且内容未变更，跳过重提
                    job.skipped_documents += 1
                    job.summary = {
                        **job.summary,
                        "progress": _progress(
                            progress_value, 3, f"跳过未变更 {index}/{total}"
                        ),
                    }
                    await session.commit()
                    continue

            spec = DocumentApiSpec(
                spec_id=f"DAS-{uuid4().hex[:12]}",
                document_id=doc.id,
                status="queued",
                created_by=job.created_by,
                summary={"progress": _progress(0, 0, "排队中")},
            )
            spec = await document_api_repo.create_spec(session, spec)
            await session.commit()

            await document_api_service.process_extraction(session, spec.id)

            spec = await document_api_repo.find_by_id(session, spec.id)
            if spec and spec.status == "completed":
                job.completed_documents += 1
                job.total_endpoints += spec.endpoint_count or 0
            else:
                job.failed_documents += 1

            job.summary = {
                **job.summary,
                "progress": _progress(progress_value, 3, f"已处理 {index}/{total}"),
            }
            await session.commit()

        job.status = "completed"
        job.finished_at = _now()
        job.summary = {**job.summary, "progress": _progress(100, 4, "完成")}
        await session.commit()
        await session.refresh(job)

        if (job.total_endpoints or 0) > 0:
            await _enqueue_auto_classify(session, job)

        return _serialize_batch_job(job)
    except Exception as exc:
        logger.exception("library batch extraction failed: job_pk=%s", job_pk)
        await session.rollback()
        job = await document_api_repo.find_batch_by_id(session, job_pk)
        if job and job.status in ("queued", "running"):
            await _fail_job(session, job, f"批量提取执行失败: {exc}"[:500])
        return _serialize_batch_job(job) if job else {}


async def _fail_job(
    session: AsyncSession, job: DocumentApiBatchJob, message: str
) -> None:
    job.status = "failed"
    job.error_message = message[:500]
    job.finished_at = _now()
    job.summary = {**job.summary, "progress": _progress(100, 4, "失败")}
    await session.commit()
    await session.refresh(job)


async def fail_batch_by_id(job_pk: int, message: str) -> None:
    """Celery 异常处理器调用：自起 session 标记失败。"""
    async with get_worker_session_factory()() as session:
        job = await document_api_repo.find_batch_by_id(session, job_pk)
        if job and job.status in ("queued", "running"):
            await _fail_job(session, job, message)


async def _enqueue_auto_classify(
    session: AsyncSession, job: DocumentApiBatchJob
) -> None:
    """批量提取完成后自动派发库级分类（尽力而为，失败仅记日志）。

    分类模型走平台默认模型，复用发起人，分类失败不影响提取已完成的事实。
    """
    try:
        from services import document_api_classify_service

        await document_api_classify_service.create_classification(
            session, job.library, {"id": job.created_by}
        )
        logger.info("auto classify enqueued: library=%s", job.library)
    except (ConflictError, NotFoundError, ValidationError) as exc:
        logger.info("auto classify skipped: library=%s reason=%s", job.library, exc)


# ── 前端读取 ──────────────────────────────────────────────────────────────────


async def get_library_extraction_status(
    session: AsyncSession, library_name: str
) -> dict | None:
    job = await document_api_repo.find_latest_batch_by_library(session, library_name)
    return _serialize_batch_job(job) if job else None


async def preview_library_extraction(session: AsyncSession, library_name: str) -> dict:
    """预览库级提取：列出将提取（新增/变更）与将跳过（未变更）的文档，不执行提取。

    供前端确认弹窗展示。分类逻辑与 process_library_extraction 的增量判断一致：
    有 content_hash + 已有接口 + hash 未变 → 跳过；否则需提取（new/changed）。
    批量查询 counts/hashes，避免逐文档 N+1。
    """
    docs = await document_repo.list_by_ingest_status(
        session, ["ingested"], library=library_name
    )
    counts = await document_api_repo.count_endpoints_grouped_by_library(
        session, library_name
    )
    latest_hashes = await document_api_repo.latest_completed_hash_by_library(
        session, library_name
    )

    to_extract: list[dict] = []
    skipped: list[dict] = []
    new_count = 0
    changed_count = 0
    for doc in docs:
        title = doc.title or f"document-{doc.id}"
        existing = counts.get(doc.id, 0)
        latest_hash = latest_hashes.get(doc.id)
        if doc.content_hash and existing > 0 and latest_hash == doc.content_hash:
            skipped.append({"id": doc.id, "title": title})
        else:
            reason = "new" if existing == 0 else "changed"
            if reason == "new":
                new_count += 1
            else:
                changed_count += 1
            to_extract.append({"id": doc.id, "title": title, "reason": reason})

    return {
        "to_extract": to_extract,
        "skipped": skipped,
        "summary": {
            "new": new_count,
            "changed": changed_count,
            "skipped": len(skipped),
        },
    }
