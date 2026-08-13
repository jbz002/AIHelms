"""AI 接口提取服务。

异步流程（仿 ai_policies audit）：create_extraction 建 job 行 → Celery worker 跑
process_extraction → LLM 提取 → 结构化落 document_api_endpoints → build_openapi_spec
聚合给前端 Scalar 渲染。

LLM 调用走平台 key（services/platform_llm.py，复用 LITELLM_MASTER_KEY），
管理员无感，无需个人 AiKey。
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
    document_api_repo,
    document_repo,
    user_repo,
)
from services import litellm_client, platform_llm, platform_settings_service

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
    '{"method":"POST","path":"/api/v1/users","summary":"创建用户",'
    '"description":"新建一个用户并返回。","operation_id":"createUser","tags":["用户"],'
    '"parameters":[{"name":"X-Trace-Id","in":"header","required":false,'
    '"description":"链路追踪 ID","schema":{"type":"string"}}],'
    '"request_body":{"content":{"application/json":{"schema":{"type":"object","properties":{'
    '"name":{"type":"string","description":"用户名"},'
    '"email":{"type":"string","format":"email","description":"邮箱地址"},'
    '"roles":{"type":"array","items":{"type":"string"},"description":"角色列表"},'
    '"profile":{"type":"object","description":"扩展资料","properties":{'
    '"age":{"type":"integer","description":"年龄"},'
    '"city":{"type":"string","description":"所在城市"}}}},'
    '"required":["name","email"]}}}},'
    '"responses":{"201":{"description":"创建成功","content":{"application/json":{"schema":'
    '{"type":"object","properties":{'
    '"id":{"type":"integer","description":"用户 ID"},'
    '"name":{"type":"string","description":"用户名"},'
    '"email":{"type":"string","description":"邮箱地址"}},'
    '"required":["id"]}}}}}}]}'
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
        "- 每个 parameter 必须含中文 description 说明其含义\n"
        "- request_body 与每个响应的 schema 必须展开 properties：每个字段给出 type 与"
        "中文 description；嵌套对象继续递归展开其 properties；数组字段用 items 描述元素结构；"
        "用 required 数组标注必填字段\n"
        "- schema 用 inline 结构，禁止使用 $ref\n"
        "- 仅当文档确实未提及参数/请求体/响应结构时才填空"
        "（parameters=[]、request_body={}、responses={}）\n"
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
        "max_tokens": 12000,
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
    current_user: dict,
) -> dict:
    doc = await document_repo.find_by_id(session, document_id)
    if doc is None:
        raise NotFoundError("document", document_id)
    if not doc.content or not doc.content.strip():
        raise ValidationError("文档内容为空，无法提取接口")
    if await document_api_repo.find_active_by_document(session, document_id):
        raise ConflictError("该文档已有接口提取任务在进行中")

    spec = DocumentApiSpec(
        spec_id=f"DAS-{uuid4().hex[:12]}",
        document_id=document_id,
        status="queued",
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


async def _resolve_actor(session: AsyncSession, spec: DocumentApiSpec) -> object | None:
    """解析发起人（LiteLLM user 归属 + metadata）。不在/停用返回 None。

    平台 key 调用不需要个人 AiKey；发起人仅作日志归属。
    """
    user = await user_repo.find_user_by_id(session, int(spec.created_by or 0))
    if not user or not getattr(user, "is_active", False):
        return None
    return user


async def process_extraction(session: AsyncSession, spec_pk: int) -> dict:
    spec = await document_api_repo.find_by_id(session, spec_pk)
    if spec is None or spec.status not in ("queued", "running"):
        return {}

    spec.status = "running"
    spec.started_at = _now()
    spec.summary = {**spec.summary, "progress": _progress(10, 1, "初始化")}
    await session.commit()

    try:
        user = await _resolve_actor(session, spec)
        if user is None:
            await _fail_spec(session, spec, "发起账号不存在或已停用")
            return _serialize_spec(spec)
        resolved = await platform_settings_service.resolve_default_model(session)
        if resolved is None:
            await _fail_spec(session, spec, "平台未配置默认模型，请在平台设置中配置")
            return _serialize_spec(spec)
        model_id, model_name = resolved
        spec.model_id = model_id
        platform_key, litellm_user_id = await platform_llm.resolve_call_identity(
            session, user, model_name
        )
        if not platform_key:
            await _fail_spec(session, spec, "平台未配置 LLM 主密钥(LITELLM_MASTER_KEY)")
            return _serialize_spec(spec)

        doc = await document_repo.find_by_id(session, spec.document_id)
        if doc is None or not (doc.content or "").strip():
            await _fail_spec(session, spec, "文档不存在或内容为空")
            return _serialize_spec(spec)

        spec.model_name = model_name
        spec.content_hash = doc.content_hash or ""
        spec.summary = {**spec.summary, "progress": _progress(30, 2, "调用模型提取")}
        await session.commit()

        metadata = {
            "aihelms_feature": "document_api_extract",
            "aihelms_spec_id": spec.spec_id,
            "aihelms_document_id": spec.document_id,
            "aihelms_user_id": user.id,
            "aihelms_credential": "platform_master_key",
        }
        data, usage, truncated = await _run_llm_extraction(
            spec, doc, model_name, platform_key, litellm_user_id, metadata
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
        await session.refresh(spec)
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
    await session.refresh(spec)


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
