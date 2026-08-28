"""工具调用探针：发带 tools 的真实请求，校验响应含结构化工具调用。

背景：2026-08-26（anthropic 方言）与 2026-08-27（openai 方言）两次生产事故均为
路由前缀错配走 litellm 翻译层，tool_call 被打平成文本——HTTP 层 success、
日志 success，唯独工具调用静默残废。连通性测试（无 tools）测不出这类错配；
探针用强制 tool_choice + 打平指纹检测，把「静默降级」变成配置时可见的显性结论。
判定只依赖协议约定（请求了工具则响应必须含结构化工具调用），不依赖供应商知识。
"""

import json
import logging
from collections.abc import AsyncGenerator

import httpx

from core.config import settings
from services.access_test_error_mapper import map_error

logger = logging.getLogger(__name__)

PROBE_TOOL_NAME = "probe_echo"
PROBE_INSTRUCTION = "调用 probe_echo 工具，参数 text=ok。不要用文字回答。"
PROBE_MAX_TOKENS = 64
# litellm 翻译层丢工具后的典型指纹：工具调用以裸 JSON 文本流出
FLATTENED_FINGERPRINT = "function_call"

_FLATTENED_DETAIL = "工具调用被打平成文本，疑似路由前缀错配走了 litellm 翻译层"
_NO_TOOL_DETAIL = "响应未包含结构化工具调用，tools 声明可能在链路上被丢弃"

_PROBE_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def _verdict(stream: bool, ok: bool, detail: str) -> dict:
    return {"mode": "stream" if stream else "nonstream", "ok": ok, "detail": detail}


# --- 判定（纯函数，输入为解析后的响应 JSON） ---


def judge_openai_nonstream(payload: dict) -> dict:
    """非流式 openai 协议：choices[0].message 里找 tool_calls。"""
    choices = payload.get("choices") or []
    if not choices:
        return _verdict(False, False, "响应无 choices 结构")
    message = choices[0].get("message") or {}
    if message.get("tool_calls"):
        return _verdict(False, True, "返回结构化 tool_calls")
    content = message.get("content") or ""
    finish = choices[0].get("finish_reason")
    if FLATTENED_FINGERPRINT in content:
        return _verdict(False, False, _FLATTENED_DETAIL)
    return _verdict(False, False, f"{_NO_TOOL_DETAIL}（finish_reason={finish}）")


def judge_openai_stream(chunks: list[dict]) -> dict:
    """流式 openai 协议：delta 里找 tool_calls，content 累积查指纹。"""
    content = ""
    finish = ""
    for chunk in chunks:
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        if delta.get("tool_calls"):
            return _verdict(True, True, "返回结构化 tool_calls")
        content += delta.get("content") or ""
        if choices[0].get("finish_reason"):
            finish = choices[0]["finish_reason"]
    if FLATTENED_FINGERPRINT in content:
        return _verdict(True, False, _FLATTENED_DETAIL)
    return _verdict(True, False, f"{_NO_TOOL_DETAIL}（finish_reason={finish}）")


def judge_anthropic_nonstream(payload: dict) -> dict:
    """非流式 anthropic 协议：content 块里找 tool_use。"""
    blocks = payload.get("content") or []
    if any(b.get("type") == "tool_use" for b in blocks):
        return _verdict(False, True, "返回 tool_use 块")
    stop_reason = payload.get("stop_reason")
    if stop_reason == "tool_use":
        return _verdict(False, True, "stop_reason=tool_use")
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    if FLATTENED_FINGERPRINT in text:
        return _verdict(False, False, _FLATTENED_DETAIL)
    return _verdict(False, False, f"{_NO_TOOL_DETAIL}（stop_reason={stop_reason}）")


def judge_anthropic_stream(events: list[dict]) -> dict:
    """流式 anthropic 协议：content_block_start 找 tool_use 块。"""
    text = ""
    stop_reason = ""
    for event in events:
        etype = event.get("type")
        if etype == "content_block_start":
            if (event.get("content_block") or {}).get("type") == "tool_use":
                return _verdict(True, True, "返回 tool_use 块")
        elif etype == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                text += delta.get("text") or ""
        elif etype == "message_delta":
            stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
    if FLATTENED_FINGERPRINT in text:
        return _verdict(True, False, _FLATTENED_DETAIL)
    return _verdict(True, False, f"{_NO_TOOL_DETAIL}（stop_reason={stop_reason}）")


# --- 请求构造与执行 ---


def _build_body(protocol: str, model: str, stream: bool, force: bool = True) -> dict:
    message = {"role": "user", "content": PROBE_INSTRUCTION}
    body: dict = {
        "model": model,
        "max_tokens": PROBE_MAX_TOKENS,
        "stream": stream,
        "messages": [message],
    }
    if protocol == "anthropic":
        body["tools"] = [
            {
                "name": PROBE_TOOL_NAME,
                "description": "回显文本，仅用于接入探针",
                "input_schema": _PROBE_TOOL_PARAMETERS,
            }
        ]
        if force:
            body["tool_choice"] = {"type": "tool", "name": PROBE_TOOL_NAME}
    else:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": PROBE_TOOL_NAME,
                    "description": "回显文本，仅用于接入探针",
                    "parameters": _PROBE_TOOL_PARAMETERS,
                },
            }
        ]
        if force:
            body["tool_choice"] = {
                "type": "function",
                "function": {"name": PROBE_TOOL_NAME},
            }
    return body


def _anthropic_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def _endpoint_and_headers(protocol: str, api_key: str) -> tuple[str, dict[str, str]]:
    if protocol == "anthropic":
        return (
            f"{settings.litellm_url}/v1/messages",
            _anthropic_headers(api_key),
        )
    return (
        f"{settings.litellm_url}/v1/chat/completions",
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )


async def _send(
    http_client: httpx.AsyncClient,
    protocol: str,
    api_key: str,
    body: dict,
    stream: bool,
) -> tuple[int, object]:
    url, headers = _endpoint_and_headers(protocol, api_key)
    if not stream:
        response = await http_client.post(url, headers=headers, json=body)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, response.text
    collected: list[dict] = []
    async with http_client.stream("POST", url, headers=headers, json=body) as response:
        if response.status_code != 200:
            await response.aread()
            return response.status_code, response.text
        async for event in _sse_events(response):
            collected.append(event)
    return 200, collected


async def _sse_events(response: httpx.Response) -> AsyncGenerator[dict, None]:
    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        raw = line[6:]
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


async def _probe_once(
    http_client: httpx.AsyncClient,
    model: str,
    api_key: str,
    protocol: str,
    stream: bool,
) -> dict:
    body = _build_body(protocol, model, stream)
    status, payload = await _send(http_client, protocol, api_key, body, stream)
    # 个别上游不支持强制 tool_choice：去掉重试一次（缺席判定依然成立，只是不再排除模型自由发挥）
    if status != 200 and "tool_choice" in str(payload).lower():
        body = _build_body(protocol, model, stream, force=False)
        status, payload = await _send(http_client, protocol, api_key, body, stream)
    if status != 200:
        error_detail = map_error(
            status_code=status,
            response_text=payload if isinstance(payload, str) else json.dumps(payload),
        )
        detail = error_detail.get("title") or f"HTTP {status}"
        return _verdict(stream, False, f"探针请求失败：{detail}")
    if protocol == "anthropic":
        judge = judge_anthropic_stream if stream else judge_anthropic_nonstream
    else:
        judge = judge_openai_stream if stream else judge_openai_nonstream
    return judge(payload if isinstance(payload, (dict, list)) else {})


async def run_tool_probe(model: str, api_key: str, protocol: str) -> dict:
    """对目标路由组跑非流式 + 流式两个探针，聚合判定。"""
    verdicts: list[dict] = []
    async with httpx.AsyncClient(timeout=60, trust_env=False) as http_client:
        for stream in (False, True):
            try:
                verdicts.append(
                    await _probe_once(http_client, model, api_key, protocol, stream)
                )
            except Exception as e:
                logger.error("tool probe error (%s/%s): %s", model, protocol, str(e))
                error_detail = map_error(e)
                detail = error_detail.get("title") or str(e)
                verdicts.append(_verdict(stream, False, f"探针请求异常：{detail}"))
    return {
        "success": all(v["ok"] for v in verdicts),
        "protocol": protocol,
        "verdicts": verdicts,
    }
