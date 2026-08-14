import base64
import json
import logging
from collections.abc import AsyncGenerator

import httpx
from openai import AsyncOpenAI

from core.config import settings
from services.access_test_error_mapper import build_failure, map_error

logger = logging.getLogger(__name__)


def _get_client(api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key,
        base_url=f"{settings.litellm_url}/v1",
    )


async def test_error_stream(
    error_detail: dict[str, object],
) -> AsyncGenerator[str, None]:
    yield f"data: [ERROR] {json.dumps(error_detail, ensure_ascii=False)}\n\n"


async def test_model_stream(
    model: str,
    messages: list[dict],
    max_tokens: int = 100,
    api_key: str = "",
    protocol: str = "openai",
) -> AsyncGenerator[str, None]:
    """Stream chat completion from LiteLLM, yield SSE-formatted chunks."""
    if protocol == "anthropic":
        async for chunk in _stream_anthropic(model, messages, max_tokens, api_key):
            yield chunk
        return
    client = _get_client(api_key)
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            max_tokens=max_tokens,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta:
                text = delta.content or ""
                if (
                    not text
                    and hasattr(delta, "reasoning_content")
                    and delta.reasoning_content
                ):
                    text = delta.reasoning_content
                if text:
                    yield f"data: {text}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.error("access test stream error: %s", str(e))
        error_detail = map_error(e)
        yield f"data: [ERROR] {json.dumps(error_detail, ensure_ascii=False)}\n\n"


async def test_model_sync(
    model: str,
    messages: list[dict],
    max_tokens: int = 100,
    api_key: str = "",
    protocol: str = "openai",
) -> dict:
    """Non-streaming chat completion from LiteLLM."""
    if protocol == "anthropic":
        return await _sync_anthropic(model, messages, max_tokens, api_key)
    client = _get_client(api_key)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            max_tokens=max_tokens,
        )
        msg = response.choices[0].message if response.choices else None
        content = (msg.content if msg else "") or ""
        if (
            not content
            and msg
            and hasattr(msg, "reasoning_content")
            and msg.reasoning_content
        ):
            content = f"[思考] {msg.reasoning_content}"
        return {
            "success": True,
            "content": content,
            "model": response.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": (
                    response.usage.completion_tokens if response.usage else 0
                ),
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
        }
    except Exception as e:
        logger.error("access test sync error: %s", str(e))
        result = build_failure(map_error(e))
        result["content"] = ""
        return result


async def test_embedding(model: str, text: str, api_key: str = "") -> dict:
    """Test embedding model via LiteLLM."""
    client = _get_client(api_key)
    try:
        response = await client.embeddings.create(
            model=model,
            input=text,
        )
        embedding = response.data[0].embedding if response.data else []
        return {
            "success": True,
            "dimensions": len(embedding),
            "model": response.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
        }
    except Exception as e:
        logger.error("embedding test error: %s", str(e))
        return build_failure(map_error(e))


async def test_rerank(
    model: str,
    query: str,
    documents: list[str],
    api_key: str = "",
) -> dict:
    """Test rerank model via LiteLLM /rerank endpoint."""
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as http_client:
            response = await http_client.post(
                f"{settings.litellm_url}/rerank",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "query": query,
                    "documents": documents,
                },
            )
            if response.status_code != 200:
                return build_failure(
                    map_error(
                        status_code=response.status_code,
                        response_text=response.text,
                    )
                )
            data = response.json()
            results = data.get("results", [])
            return {
                "success": True,
                "results": [
                    {
                        "index": r.get("index"),
                        "relevance_score": r.get("relevance_score"),
                    }
                    for r in results[:5]
                ],
                "model": model,
            }
    except Exception as e:
        logger.error("rerank test error: %s", str(e))
        return build_failure(map_error(e))


def _strip_data_url(audio_base64: str) -> str:
    """剥离 data-URL 前缀(data:audio/mpeg;base64,...),返回裸 base64。"""
    if audio_base64.startswith("data:"):
        comma = audio_base64.find(",")
        if comma != -1:
            return audio_base64[comma + 1 :]
    return audio_base64


async def test_image_generation(model: str, prompt: str, api_key: str = "") -> dict:
    """通过 LiteLLM /v1/images/generations 测试文生图模型。"""
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as http_client:
            response = await http_client.post(
                f"{settings.litellm_url}/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "prompt": prompt,
                    "n": 1,
                    "size": "1024x1024",
                    "response_format": "b64_json",
                },
            )
            if response.status_code != 200:
                return build_failure(
                    map_error(
                        status_code=response.status_code,
                        response_text=response.text,
                    )
                )
            images = response.json().get("data", [])
            b64_json = images[0].get("b64_json") if images else None
            if not b64_json:
                return build_failure(
                    map_error(status_code=502, response_text="上游未返回图像数据")
                )
            return {"success": True, "b64_json": b64_json, "model": model}
    except Exception as e:
        logger.error("image generation test error: %s", str(e))
        return build_failure(map_error(e))


async def test_audio_speech(model: str, text: str, api_key: str = "") -> dict:
    """通过 LiteLLM /v1/audio/speech 测试语音合成模型。"""
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as http_client:
            response = await http_client.post(
                f"{settings.litellm_url}/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": text,
                    "voice": "alloy",
                    "response_format": "mp3",
                },
            )
            if response.status_code != 200:
                return build_failure(
                    map_error(
                        status_code=response.status_code,
                        response_text=response.text,
                    )
                )
            content_type = response.headers.get("content-type", "audio/mpeg")
            b64_audio = base64.b64encode(response.content).decode("ascii")
            return {
                "success": True,
                "b64_audio": b64_audio,
                "content_type": content_type,
                "model": model,
            }
    except Exception as e:
        logger.error("audio speech test error: %s", str(e))
        return build_failure(map_error(e))


async def test_audio_transcription(
    model: str, audio_base64: str, api_key: str = ""
) -> dict:
    """通过 LiteLLM /v1/audio/transcriptions 测试语音识别模型。"""
    try:
        raw_bytes = base64.b64decode(_strip_data_url(audio_base64))
    except Exception as e:
        logger.error("audio transcription decode error: %s", str(e))
        return build_failure(map_error(e))
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as http_client:
            response = await http_client.post(
                f"{settings.litellm_url}/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("test.mp3", raw_bytes, "audio/mpeg")},
                data={"model": model},
            )
            if response.status_code != 200:
                return build_failure(
                    map_error(
                        status_code=response.status_code,
                        response_text=response.text,
                    )
                )
            return {
                "success": True,
                "text": response.json().get("text", ""),
                "model": model,
            }
    except Exception as e:
        logger.error("audio transcription test error: %s", str(e))
        return build_failure(map_error(e))


def _anthropic_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def _to_anthropic_image(url: str) -> dict:
    """OpenAI image_url 块转 Anthropic image 块:data-URL 转 base64 source,http(s) 转 url source。"""
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        media_type = "image/png"
        if ":" in header and ";" in header:
            media_type = header.split(":", 1)[1].split(";", 1)[0]
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
    return {"type": "image", "source": {"type": "url", "url": url}}


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """OpenAI messages 转 Anthropic messages:string content 原样,list content 按块映射。"""
    result: list[dict] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        if isinstance(content, str):
            result.append({"role": role, "content": content})
            continue
        if isinstance(content, list):
            blocks: list[dict] = []
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    blocks.append({"type": "text", "text": block.get("text", "")})
                elif btype == "image_url":
                    url = (block.get("image_url") or {}).get("url", "")
                    if url:
                        blocks.append(_to_anthropic_image(url))
            result.append({"role": role, "content": blocks})
    return result


async def _stream_anthropic(
    model: str,
    messages: list[dict],
    max_tokens: int,
    api_key: str,
) -> AsyncGenerator[str, None]:
    """流式调用 LiteLLM /v1/messages(Anthropic 协议),归一为 data: <text>。"""
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as http_client:
            async with http_client.stream(
                "POST",
                f"{settings.litellm_url}/v1/messages",
                headers=_anthropic_headers(api_key),
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": _to_anthropic_messages(messages),
                    "stream": True,
                },
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    error_detail = map_error(
                        status_code=response.status_code,
                        response_text=response.text,
                    )
                    yield f"data: [ERROR] {json.dumps(error_detail, ensure_ascii=False)}\n\n"
                    return
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    etype = obj.get("type")
                    if etype == "error":
                        error_detail = map_error(
                            response_text=json.dumps(
                                obj.get("error") or {}, ensure_ascii=False
                            )
                        )
                        yield f"data: [ERROR] {json.dumps(error_detail, ensure_ascii=False)}\n\n"
                        return
                    if etype == "content_block_delta":
                        delta = obj.get("delta") or {}
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            text = delta.get("text") or ""
                        elif dtype == "thinking_delta":
                            text = delta.get("thinking") or ""
                        else:
                            text = ""
                        if text:
                            yield f"data: {text}\n\n"
                yield "data: [DONE]\n\n"
    except Exception as e:
        logger.error("access test anthropic stream error: %s", str(e))
        yield f"data: [ERROR] {json.dumps(map_error(e), ensure_ascii=False)}\n\n"


async def _sync_anthropic(
    model: str,
    messages: list[dict],
    max_tokens: int,
    api_key: str,
) -> dict:
    """非流式调用 LiteLLM /v1/messages(Anthropic 协议)。"""
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as http_client:
            response = await http_client.post(
                f"{settings.litellm_url}/v1/messages",
                headers=_anthropic_headers(api_key),
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": _to_anthropic_messages(messages),
                },
            )
            if response.status_code != 200:
                return build_failure(
                    map_error(
                        status_code=response.status_code,
                        response_text=response.text,
                    )
                )
            data = response.json()
            content_blocks = data.get("content") or []
            text = "".join(
                b.get("text", "") for b in content_blocks if b.get("type") == "text"
            )
            usage = data.get("usage") or {}
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            return {
                "success": True,
                "content": text,
                "model": data.get("model"),
                "usage": {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
            }
    except Exception as e:
        logger.error("access test anthropic sync error: %s", str(e))
        result = build_failure(map_error(e))
        result["content"] = ""
        return result
