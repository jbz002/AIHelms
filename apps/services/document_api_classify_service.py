"""库级 AI 接口分类服务。

独立分类步骤：拉库内全部已提取 endpoints，AI 按业务模块/资源域统一归类，
回写 DocumentApiEndpoint.category。Celery worker 调 process_classification。
另提供 build_library_endpoints 聚合库级接口（扁平 + operation 内联）供前端渲染。

复用 document_api_service 的 _call_llm / _extract_json / _response_text（同包）。
LLM 调用走平台 key（services/platform_llm.py，复用 LITELLM_MASTER_KEY）。
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_worker_session_factory
from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import DocumentApiCategoryJob, DocumentApiEndpoint
from repositories import document_api_repo, model_repo, user_repo
from services import document_api_service, platform_llm

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _progress(value: int, step: str) -> dict:
    return {"value": value, "step": step}


def _serialize_category_job(job: DocumentApiCategoryJob) -> dict:
    return {
        "id": job.id,
        "job_id": job.job_id,
        "library": job.library,
        "status": job.status,
        "model_id": job.model_id,
        "model_name": job.model_name,
        "endpoint_count": job.endpoint_count,
        "category_count": job.category_count,
        "prompt_tokens": job.prompt_tokens,
        "completion_tokens": job.completion_tokens,
        "categories": job.categories or [],
        "summary": job.summary or {},
        "error_message": job.error_message,
        "created_by": job.created_by,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


# ── Prompt ────────────────────────────────────────────────────────────────────


def _build_classify_messages(
    endpoints: list[DocumentApiEndpoint], retry: bool
) -> list[dict]:
    lines = [
        f"{i}\t{ep.method}\t{ep.path}\t{ep.summary or ''}"
        for i, ep in enumerate(endpoints)
    ]
    listing = "\n".join(lines)
    retry_hint = (
        "\n上一次输出未解析为合法 JSON，请严格只输出合法 JSON 对象。" if retry else ""
    )
    user_text = (
        "任务：将下列 API 接口按业务模块/资源域归类为单层分类。\n"
        "要求：\n"
        "- 分类名简洁中文（2-6 字），如「用户管理」「订单管理」「权限」「统计」\n"
        "- 同类接口归同一分类名，不嵌套子分类\n"
        "- 每个接口必须归入一个分类\n\n"
        "接口列表（格式：序号\\t方法\\t路径\\t摘要）：\n"
        f"{listing}\n\n"
        '输出 JSON schema：{"items":[{"index":0,"category":"用户管理"}],'
        '"categories":["用户管理","订单管理"]}\n'
        "index 对应输入序号，categories 为去重后的全部分类名。"
        f"{retry_hint}"
    )
    return [
        {
            "role": "system",
            "content": "你是 API 接口分类专家。按业务模块对接口归类，输出严格 JSON。",
        },
        {"role": "user", "content": user_text},
    ]


async def _run_llm_classify(
    endpoints: list[DocumentApiEndpoint],
    model_name: str,
    api_key: str,
    user_id: str,
    metadata: dict,
) -> tuple[dict | None, dict]:
    """调 LLM 分类接口；解析失败重 prompt 一次。返回 (data, usage)。"""
    messages = _build_classify_messages(endpoints, retry=False)
    response = await document_api_service._call_llm(
        model_name, messages, api_key, user_id, metadata
    )
    usage = response.get("usage", {}) or {}
    data = document_api_service._extract_json(
        document_api_service._response_text(response)
    )
    if data is not None:
        return data, usage

    messages = _build_classify_messages(endpoints, retry=True)
    response = await document_api_service._call_llm(
        model_name, messages, api_key, user_id, metadata
    )
    usage = response.get("usage", {}) or {}
    return (
        document_api_service._extract_json(
            document_api_service._response_text(response)
        ),
        usage,
    )


# ── 创建任务 ──────────────────────────────────────────────────────────────────


async def create_classification(
    session: AsyncSession, library_name: str, model_id: int, current_user: dict
) -> dict:
    if await document_api_repo.find_active_category_by_library(session, library_name):
        raise ConflictError("该库已有分类任务在进行中")
    if await model_repo.find_by_id(session, model_id) is None:
        raise NotFoundError("model", model_id)
    count = await document_api_repo.count_by_library(session, library_name)
    if count == 0:
        raise ValidationError("该库无已提取接口，请先批量提取接口")

    job = DocumentApiCategoryJob(
        job_id=f"DAC-{uuid4().hex[:12]}",
        library=library_name,
        status="queued",
        model_id=model_id,
        created_by=int(current_user["id"]),
        summary={"progress": _progress(0, "排队中")},
    )
    job = await document_api_repo.create_category_job(session, job)
    await session.commit()
    await session.refresh(job)

    from tasks.document_api_tasks import classify_library_interfaces_task

    classify_library_interfaces_task.delay(job.id)
    return _serialize_category_job(job)


# ── worker 体 ─────────────────────────────────────────────────────────────────


async def process_classification(session: AsyncSession, job_pk: int) -> dict:
    job = await document_api_repo.find_category_by_id(session, job_pk)
    if job is None or job.status not in ("queued", "running"):
        return {}

    job.status = "running"
    job.started_at = _now()
    job.summary = {**job.summary, "progress": _progress(10, "初始化")}
    await session.commit()

    try:
        user = await user_repo.find_user_by_id(session, int(job.created_by or 0))
        if not user or not getattr(user, "is_active", False):
            await _fail_job(session, job, "发起账号不存在或已停用")
            return _serialize_category_job(job)
        platform_key = platform_llm.get_platform_api_key()
        if not platform_key:
            await _fail_job(session, job, "平台未配置 LLM 主密钥(LITELLM_MASTER_KEY)")
            return _serialize_category_job(job)
        litellm_user_id = platform_llm.platform_user(user)

        model = (
            await model_repo.find_by_id(session, job.model_id) if job.model_id else None
        )
        if model is None:
            await _fail_job(session, job, "所选模型不存在")
            return _serialize_category_job(job)
        model_name = getattr(model, "model_id", "") or getattr(model, "name", "")
        if not model_name:
            await _fail_job(session, job, "所选模型不可用")
            return _serialize_category_job(job)

        endpoints = await document_api_repo.list_by_library(session, job.library)
        if not endpoints:
            await _fail_job(session, job, "该库无已提取接口，请先批量提取接口")
            return _serialize_category_job(job)

        job.model_name = model_name
        job.endpoint_count = len(endpoints)
        job.summary = {**job.summary, "progress": _progress(40, "调用模型分类")}
        await session.commit()

        metadata = {
            "aihelms_feature": "document_api_classify",
            "aihelms_job_id": job.job_id,
            "aihelms_library": job.library,
            "aihelms_user_id": user.id,
            "aihelms_credential": "platform_master_key",
        }
        data, usage = await _run_llm_classify(
            endpoints, model_name, platform_key, litellm_user_id, metadata
        )
        if data is None:
            await _fail_job(session, job, "模型输出无法解析为合法 JSON")
            return _serialize_category_job(job)

        updates = _map_categories(data, endpoints)
        await document_api_repo.bulk_update_category(session, updates)
        categories = _collect_categories(data)

        job.status = "completed"
        job.finished_at = _now()
        job.category_count = len(categories)
        job.categories = categories
        job.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        job.completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        job.raw_output = data
        job.summary = {**job.summary, "progress": _progress(100, "完成")}
        await session.commit()
        await session.refresh(job)
        return _serialize_category_job(job)
    except Exception as exc:
        logger.exception("library classification failed: job_pk=%s", job_pk)
        await session.rollback()
        job = await document_api_repo.find_category_by_id(session, job_pk)
        if job and job.status in ("queued", "running"):
            await _fail_job(session, job, f"分类执行失败: {exc}"[:500])
        return _serialize_category_job(job) if job else {}


def _map_categories(
    data: dict, endpoints: list[DocumentApiEndpoint]
) -> list[tuple[int, str]]:
    """按 index 映射回 endpoint.id，返回 (endpoint_id, category) 列表。"""
    items = data.get("items", []) if isinstance(data, dict) else []
    updates: list[tuple[int, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        category = str(item.get("category", "")).strip()
        if idx is None or not category:
            continue
        try:
            i = int(idx)
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(endpoints):
            updates.append((endpoints[i].id, category))
    return updates


def _collect_categories(data: dict) -> list[str]:
    """从模型输出提取去重后的分类名清单（保留顺序）。"""
    cats: list[str] = []
    seen: set[str] = set()
    items = data.get("items", []) if isinstance(data, dict) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        c = str(item.get("category", "")).strip()
        if c and c not in seen:
            seen.add(c)
            cats.append(c)
    return cats


async def _fail_job(
    session: AsyncSession, job: DocumentApiCategoryJob, message: str
) -> None:
    job.status = "failed"
    job.error_message = message[:500]
    job.finished_at = _now()
    job.summary = {**job.summary, "progress": _progress(100, "失败")}
    await session.commit()
    await session.refresh(job)


async def fail_category_by_id(job_pk: int, message: str) -> None:
    """Celery 异常处理器调用：自起 session 标记失败。"""
    async with get_worker_session_factory()() as session:
        job = await document_api_repo.find_category_by_id(session, job_pk)
        if job and job.status in ("queued", "running"):
            await _fail_job(session, job, message)


# ── 前端读取 ──────────────────────────────────────────────────────────────────


async def get_classification_status(
    session: AsyncSession, library_name: str
) -> dict | None:
    job = await document_api_repo.find_latest_category_by_library(session, library_name)
    return _serialize_category_job(job) if job else None


def _serialize_endpoint_with_operation(ep: DocumentApiEndpoint) -> dict:
    return {
        "id": ep.id,
        "document_id": ep.document_id,
        "method": ep.method.lower(),
        "path": ep.path,
        "summary": ep.summary,
        "category": ep.category,
        "operation": {
            "summary": ep.summary,
            "description": ep.description,
            "operationId": ep.operation_id,
            "tags": ep.tags or [],
            "parameters": ep.parameters or [],
            "requestBody": ep.request_body or {},
            "responses": ep.responses or {},
        },
    }


async def build_library_endpoints(session: AsyncSession, library_name: str) -> dict:
    endpoints = await document_api_repo.list_by_library(session, library_name)
    return {
        "library": library_name,
        "total": len(endpoints),
        "endpoints": [_serialize_endpoint_with_operation(ep) for ep in endpoints],
    }
