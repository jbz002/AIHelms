"""文档库 AI 摘要搜索（SSE 流式）。

流程：docs_mcp_client.search 取检索片段 → 拼 prompt →
litellm_client.chat_completion_stream 流式输出 Markdown 摘要。
只读、无 DB 任务行；模型走平台默认模型配置（platform_settings_service）。
"""

import json
import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services import litellm_client, platform_llm, platform_settings_service
from services.docs_mcp_client import docs_mcp_client

logger = logging.getLogger(__name__)

MAX_CHUNKS = 8
CHUNK_CONTENT_CHARS = 1500


def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_sources(chunks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    sources: list[dict] = []
    for chunk in chunks:
        url = chunk.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append({"url": url, "score": chunk.get("score")})
    return sources


def _build_messages(query: str, chunks: list[dict]) -> list[dict]:
    pieces: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        url = chunk.get("url", "")
        content = (chunk.get("content") or "")[:CHUNK_CONTENT_CHARS]
        pieces.append(f"[{idx}] url={url}\n{content}")
    context = "\n---\n".join(pieces)
    user_text = (
        f"用户问题：{query}\n\n"
        f"以下是按相关度排序的检索片段（共 {len(chunks)} 条）：\n"
        f"{context}\n\n"
        "请依据上述片段用中文 Markdown 回答用户问题。要求：\n"
        "- 仅基于片段内容，不臆测片段外的信息\n"
        "- 在陈述后用 [n] 标注来源编号，对应上方片段序号\n"
        "- 片段不足以回答时，如实说明还缺什么\n"
    )
    return [
        {
            "role": "system",
            "content": "你是文档检索摘要助手。依据检索片段组织清晰、结构化的中文 Markdown 回答，"
            "不编造片段外的内容。",
        },
        {"role": "user", "content": user_text},
    ]


async def stream_summary(
    session: AsyncSession,
    library: str,
    query: str,
    version: str | None,
    current_user: dict,
) -> AsyncIterator[str]:
    resolved = await platform_settings_service.resolve_default_model(session)
    if resolved is None:
        yield sse("error", {"message": "平台未配置默认模型，请在平台设置中配置"})
        return
    _, model_name = resolved

    platform_key = platform_llm.get_platform_api_key()
    if not platform_key:
        yield sse("error", {"message": "平台未配置 LLM 主密钥(LITELLM_MASTER_KEY)"})
        return
    litellm_user_id = platform_llm.platform_user(current_user)

    try:
        chunks = await docs_mcp_client.search(
            library=library, query=query, version=version, limit=MAX_CHUNKS
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("doc summary search failed: library=%s", library)
        yield sse("error", {"message": f"检索失败：{exc}"[:200]})
        return

    if not chunks:
        yield sse("error", {"message": "未找到相关文档"})
        return

    yield sse("sources", _build_sources(chunks))

    messages = _build_messages(query, chunks)
    metadata = {
        "aihelms_feature": "doc_search_summary",
        "aihelms_library": library,
        "aihelms_user_id": current_user.get("id"),
        "aihelms_credential": "platform_master_key",
    }

    prompt_tokens = 0
    completion_tokens = 0
    finish_reason = "stop"
    try:
        async for chunk in litellm_client.chat_completion_stream(
            model=model_name,
            messages=messages,
            temperature=0.2,
            max_tokens=1200,
            timeout=120.0,
            api_key=platform_key,
            user=litellm_user_id,
            metadata=metadata,
        ):
            choices = chunk.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                content = delta.get("content") or ""
                if content:
                    yield sse("delta", {"content": content})
                fr = choices[0].get("finish_reason")
                if fr:
                    finish_reason = fr
            usage = chunk.get("usage")
            if usage:
                prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
                completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        logger.exception("doc summary llm stream failed: library=%s", library)
        yield sse("error", {"message": f"模型调用失败：{exc}"[:200]})
        return

    yield sse(
        "done",
        {
            "finish_reason": finish_reason,
            "model": model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    )
