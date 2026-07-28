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
from repositories import document_api_repo, document_repo, model_repo
from services import document_api_service, platform_llm

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _progress(value: int, completed: int, step: str) -> dict:
    return {"value": value, "completed": completed, "total": 4, "step": step}


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
    session: AsyncSession, library_name: str, model_id: int, current_user: dict
) -> dict:
    docs = await document_repo.list_by_ingest_status(
        session, ["ingested"], library=library_name
    )
    if not docs:
        raise ValidationError("该库无已入库文档，无法批量提取")
    if await document_api_repo.find_active_batch_by_library(session, library_name):
        raise ConflictError("该库已有批量提取任务在进行中")
    if await model_repo.find_by_id(session, model_id) is None:
        raise NotFoundError("model", model_id)

    job = DocumentApiBatchJob(
        job_id=f"DAB-{uuid4().hex[:12]}",
        library=library_name,
        status="queued",
        model_id=model_id,
        total_documents=len(docs),
        created_by=int(current_user["id"]),
        summary={"progress": _progress(0, 0, "排队中")},
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

    job.status = "running"
    job.started_at = _now()
    job.summary = {**job.summary, "progress": _progress(10, 1, "初始化")}
    await session.commit()

    try:
        if not platform_llm.get_platform_api_key():
            await _fail_job(session, job, "平台未配置 LLM 主密钥(LITELLM_MASTER_KEY)")
            return _serialize_batch_job(job)

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

            spec = DocumentApiSpec(
                spec_id=f"DAS-{uuid4().hex[:12]}",
                document_id=doc.id,
                status="queued",
                model_id=job.model_id,
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

    复用提取所用模型与发起人，分类失败不影响提取已完成的事实。
    """
    try:
        from services import document_api_classify_service

        await document_api_classify_service.create_classification(
            session, job.library, job.model_id, {"id": job.created_by}
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
