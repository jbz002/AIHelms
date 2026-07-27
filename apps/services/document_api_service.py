"""AI 接口提取服务。

异步流程（仿 ai_policies audit）：create_extraction 建 job 行 → Celery worker 跑
process_extraction → LLM 提取 → 结构化落 document_api_endpoints → build_openapi_spec
聚合给前端 Scalar 渲染。

凭据链复用 ai_policies 已验证方案：job 行 created_by → user → 个人主 AiKey → litellm。
"""

import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_worker_session_factory
from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import Document, DocumentApiEndpoint, DocumentApiSpec
from repositories import (
    ai_key_repo,
    document_api_repo,
    document_repo,
    model_repo,
    user_repo,
)
from services import litellm_client

logger = logging.getLogger(__name__)

VALID_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _progress(value: int, completed: int, step: str) -> dict:
    return {"value": value, "completed": completed, "total": 4, "step": step}


# ── 序列化 ────────────────────────────────────────────────────────────────────


def _serialize_spec(spec: DocumentApiSpec) -> dict:
    return {
        "id": spec.id,
        "spec_id": spec.spec_id,
        "document_id": spec.document_id,
        "status": spec.status,
        "model_id": spec.model_id,
        "model_name": spec.model_name,
        "endpoint_count": spec.endpoint_count,
        "prompt_tokens": spec.prompt_tokens,
        "completion_tokens": spec.completion_tokens,
        "summary": spec.summary or {},
        "error_message": spec.error_message,
        "created_by": spec.created_by,
        "started_at": spec.started_at.isoformat() if spec.started_at else None,
        "finished_at": spec.finished_at.isoformat() if spec.finished_at else None,
        "created_at": spec.created_at.isoformat() if spec.created_at else None,
        "updated_at": spec.updated_at.isoformat() if spec.updated_at else None,
    }


# ── JSON 解析（自包含，仿 ai_policies_llm 候选 + 括号深度）────────────────────


def _try_load_object(text: str, start: int) -> dict | None:
    depth = 0
    in_string = False
    escaped = False
    for index, ch in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : index + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _extract_json(text: str) -> dict | None:
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I).strip()
    for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.S | re.I):
        start = match.group(1).find("{")
        if start >= 0:
            obj = _try_load_object(match.group(1), start)
            if obj is not None:
                return obj
    start = cleaned.find("{")
    if start >= 0:
        return _try_load_object(cleaned, start)
    return None


# ── Prompt ────────────────────────────────────────────────────────────────────

_EXTRACTION_SCHEMA = (
    '{"endpoints":['
    '{"method":"GET","path":"/api/v1/users","summary":"获取用户列表",'
    '"description":"分页返回用户。","operation_id":"listUsers","tags":["用户"],'
    '"parameters":[{"name":"page","in":"query","required":false,"schema":{"type":"integer"}}],'
    '"request_body":{"content":{"application/json":{"schema":{}}}},'
    '"responses":{"200":{"description":"成功","content":{"application/json":{"schema":{}}}}}}]}'
)


def _build_messages(title: str, content: str, retry: bool) -> list[dict]:
    retry_hint = (
        "\n上一次输出未解析为合法 JSON，请严格只输出合法 JSON 对象。" if retry else ""
    )
    user_text = (
        f"文档标题：{title}\n\n"
        f"文档内容：\n{content}\n\n"
        "任务：从上述文档中提取所有 HTTP API 接口，输出 JSON，schema 如下：\n"
        f"{_EXTRACTION_SCHEMA}\n\n"
        "要求：\n"
        "- method 仅限 GET/POST/PUT/DELETE/PATCH，大写\n"
        "- path 以 / 开头\n"
        "- 文档未提及的字段填空（parameters=[]、request_body={}、responses={}）\n"
        '- 找不到任何接口时返回 {"endpoints": []}'
        f"{retry_hint}"
    )
    return [
        {
            "role": "system",
            "content": "你是 API 接口提取专家。严格依据文档内容提取 HTTP 接口，"
            "不臆测文档未提及的接口，按指定 JSON schema 输出。",
        },
        {"role": "user", "content": user_text},
    ]


# ── LLM 调用（含 response_format/extra_body 不可用时的回退）──────────────────


async def _call_llm(
    model_name: str,
    messages: list[dict],
    api_key: str,
    user_id: str,
    metadata: dict,
) -> dict:
    common = {
        "temperature": 0,
        "max_tokens": 8000,
        "timeout": 120,
        "api_key": api_key,
        "user": user_id,
        "metadata": metadata,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    try:
        return await litellm_client.chat_completion(
            model_name,
            messages,
            response_format={"type": "json_object"},
            **common,
        )
    except Exception as exc:
        message = str(exc).lower()
        if not any(
            marker in message
            for marker in ("response_format", "json_object", "extra_body", "thinking")
        ):
            raise
        return await litellm_client.chat_completion(
            model_name,
            messages,
            **{k: v for k, v in common.items() if k != "extra_body"},
        )


def _response_text(response: dict) -> str:
    try:
        return response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        return ""


def _is_truncated(response: dict) -> bool:
    try:
        return response["choices"][0].get("finish_reason") in {
            "length",
            "max_tokens",
            "incomplete",
        }
    except (KeyError, IndexError):
        return False


def _build_endpoint(document_id: int, raw: dict) -> DocumentApiEndpoint | None:
    if not isinstance(raw, dict):
        return None
    method = str(raw.get("method", "")).strip().upper()
    path = str(raw.get("path", "")).strip()
    if method not in VALID_METHODS or not path:
        return None
    return DocumentApiEndpoint(
        document_id=document_id,
        method=method,
        path=path[:500],
        summary=str(raw.get("summary", ""))[:500],
        description=str(raw.get("description", "")),
        operation_id=str(raw.get("operation_id", raw.get("operationId", "")))[:200],
        tags=raw.get("tags") or [],
        parameters=raw.get("parameters") or [],
        request_body=raw.get("request_body") or raw.get("requestBody") or {},
        responses=raw.get("responses") or {},
    )


# ── 创建任务 ──────────────────────────────────────────────────────────────────


async def create_extraction(
    session: AsyncSession,
    document_id: int,
    model_id: int,
    current_user: dict,
) -> dict:
    doc = await document_repo.find_by_id(session, document_id)
    if doc is None:
        raise NotFoundError("document", document_id)
    if not doc.content or not doc.content.strip():
        raise ValidationError("文档内容为空，无法提取接口")
    if await document_api_repo.find_active_by_document(session, document_id):
        raise ConflictError("该文档已有接口提取任务在进行中")
    if await model_repo.find_by_id(session, model_id) is None:
        raise NotFoundError("model", model_id)

    spec = DocumentApiSpec(
        spec_id=f"DAS-{uuid4().hex[:12]}",
        document_id=document_id,
        status="queued",
        model_id=model_id,
        created_by=int(current_user["id"]),
        summary={"progress": _progress(0, 0, "排队中")},
    )
    spec = await document_api_repo.create_spec(session, spec)
    await session.commit()
    await session.refresh(spec)

    from tasks.document_api_tasks import extract_api_interfaces_task

    extract_api_interfaces_task.delay(spec.id)
    return _serialize_spec(spec)


# ── worker 体 ─────────────────────────────────────────────────────────────────


async def _resolve_credentials(
    session: AsyncSession, spec: DocumentApiSpec
) -> tuple[object, object, str] | None:
    """复用 ai_policies 凭据链：created_by → user → 个人主 Key。失败返回 None。"""
    user = await user_repo.find_user_by_id(session, int(spec.created_by or 0))
    if not user or not getattr(user, "is_active", False):
        return None
    key = await ai_key_repo.find_personal_main(session, user.id)
    if (
        not key
        or not getattr(key, "is_active", False)
        or not getattr(key, "litellm_key_id", "")
    ):
        return None
    litellm_user_id = getattr(user, "litellm_user_id", "") or f"aihelms_user_{user.id}"
    return user, key, litellm_user_id


async def process_extraction(session: AsyncSession, spec_pk: int) -> dict:
    spec = await document_api_repo.find_by_id(session, spec_pk)
    if spec is None or spec.status not in ("queued", "running"):
        return {}

    spec.status = "running"
    spec.started_at = _now()
    spec.summary = {**spec.summary, "progress": _progress(10, 1, "初始化")}
    await session.commit()

    try:
        creds = await _resolve_credentials(session, spec)
        if creds is None:
            await _fail_spec(session, spec, "发起账号未配置可用的个人主 Key")
            return _serialize_spec(spec)
        user, key, litellm_user_id = creds

        model = (
            await model_repo.find_by_id(session, spec.model_id)
            if spec.model_id
            else None
        )
        if model is None:
            await _fail_spec(session, spec, "所选模型不存在")
            return _serialize_spec(spec)
        model_name = getattr(model, "model_id", "") or getattr(model, "name", "")
        if not model_name:
            await _fail_spec(session, spec, "所选模型不可用")
            return _serialize_spec(spec)
        key_models = getattr(key, "models", []) or []
        if "*" not in key_models and model_name not in key_models:
            await _fail_spec(session, spec, "发起账号的个人主 Key 无权访问该模型")
            return _serialize_spec(spec)

        doc = await document_repo.find_by_id(session, spec.document_id)
        if doc is None or not (doc.content or "").strip():
            await _fail_spec(session, spec, "文档不存在或内容为空")
            return _serialize_spec(spec)

        spec.model_name = model_name
        spec.summary = {**spec.summary, "progress": _progress(30, 2, "调用模型提取")}
        await session.commit()

        metadata = {
            "aihelms_feature": "document_api_extract",
            "aihelms_spec_id": spec.spec_id,
            "aihelms_document_id": spec.document_id,
            "aihelms_user_id": user.id,
            "aihelms_ai_key_id": key.id,
        }
        data, usage, truncated = await _run_llm_extraction(
            spec, doc, model_name, key.litellm_key_id, litellm_user_id, metadata
        )
        if data is None:
            await _fail_spec(session, spec, "模型输出无法解析为合法 JSON")
            return _serialize_spec(spec)

        endpoints = [
            ep
            for ep in (
                _build_endpoint(spec.document_id, e) for e in data.get("endpoints", [])
            )
            if ep is not None
        ]
        await document_api_repo.replace_for_document(
            session, spec.document_id, endpoints
        )

        summary = {**spec.summary, "progress": _progress(100, 4, "完成")}
        if truncated:
            summary["warning"] = "文档过长，输出被截断，可能未提取全部接口"
        spec.status = "completed"
        spec.finished_at = _now()
        spec.endpoint_count = len(endpoints)
        spec.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        spec.completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        spec.raw_output = data
        spec.summary = summary
        await session.commit()
        return _serialize_spec(spec)
    except Exception as exc:
        logger.exception("document api extraction failed: spec_pk=%s", spec_pk)
        await session.rollback()
        spec = await document_api_repo.find_by_id(session, spec_pk)
        if spec and spec.status in ("queued", "running"):
            await _fail_spec(session, spec, f"提取执行失败: {exc}"[:500])
        return _serialize_spec(spec) if spec else {}


async def _run_llm_extraction(
    spec: DocumentApiSpec,
    doc: Document,
    model_name: str,
    api_key: str,
    user_id: str,
    metadata: dict,
) -> tuple[dict | None, dict, bool]:
    """调 LLM 提取接口；解析失败重 prompt 一次。返回 (data, usage, truncated)。"""
    messages = _build_messages(doc.title or "", doc.content or "", retry=False)
    response = await _call_llm(model_name, messages, api_key, user_id, metadata)
    usage = response.get("usage", {}) or {}
    truncated = _is_truncated(response)
    text = _response_text(response)
    data = _extract_json(text)
    if data is not None:
        return data, usage, truncated

    spec.summary = {**spec.summary, "progress": _progress(60, 3, "重新解析输出")}
    messages = _build_messages(doc.title or "", doc.content or "", retry=True)
    response = await _call_llm(model_name, messages, api_key, user_id, metadata)
    usage = response.get("usage", {}) or {}
    truncated = truncated or _is_truncated(response)
    return _extract_json(_response_text(response)), usage, truncated


async def _fail_spec(
    session: AsyncSession, spec: DocumentApiSpec, message: str
) -> None:
    spec.status = "failed"
    spec.error_message = message[:500]
    spec.finished_at = _now()
    spec.summary = {**spec.summary, "progress": _progress(100, 4, "失败")}
    await session.commit()


async def fail_spec_by_id(spec_pk: int, message: str) -> None:
    """Celery 异常处理器调用：自起 session 标记失败。"""
    async with get_worker_session_factory()() as session:
        spec = await document_api_repo.find_by_id(session, spec_pk)
        if spec and spec.status in ("queued", "running"):
            await _fail_spec(session, spec, message)


# ── 前端读取 ──────────────────────────────────────────────────────────────────


async def get_extract_status(session: AsyncSession, document_id: int) -> dict | None:
    spec = await document_api_repo.find_latest_by_document(session, document_id)
    return _serialize_spec(spec) if spec else None


async def build_openapi_spec(session: AsyncSession, document_id: int) -> dict:
    doc = await document_repo.find_by_id(session, document_id)
    if doc is None:
        raise NotFoundError("document", document_id)
    endpoints = await document_api_repo.list_by_document(session, document_id)

    paths: dict[str, dict] = {}
    for ep in endpoints:
        path_item = paths.setdefault(ep.path, {})
        operation: dict = {}
        if ep.summary:
            operation["summary"] = ep.summary
        if ep.description:
            operation["description"] = ep.description
        if ep.operation_id:
            operation["operationId"] = ep.operation_id
        if ep.tags:
            operation["tags"] = ep.tags
        if ep.parameters:
            operation["parameters"] = ep.parameters
        if ep.request_body:
            operation["requestBody"] = ep.request_body
        if ep.responses:
            operation["responses"] = ep.responses
        path_item[ep.method.lower()] = operation

    return {
        "openapi": "3.1.0",
        "info": {
            "title": doc.title or f"document-{document_id}",
            "version": doc.version or "1.0.0",
        },
        "paths": paths,
    }
