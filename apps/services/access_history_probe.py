"""历史回放探针：校验带 thinking / 工具结果的历史在链路上可继续对话。

背景（对齐 cc-switch 跨模型会话切换的痛点）：用户切换模型后，历史消息里可能带着
上一模型签发的 thinking 块、tool_use 与 tool_result。翻译路径若丢弃或改写这些块，
第二轮会 400。工具探针只测单轮，Thinking 探针只回放 thinking+text，都不覆盖
「thinking + 工具结果」组合。

判定只依赖协议约定：第一轮产生的 assistant 内容（含 thinking/tool_use）原样回放，
配对的 tool_result 回传，第二轮应被接受（HTTP 200）。
"""

import json
import logging

import httpx

from core.config import settings
from services.access_test_error_mapper import map_error

logger = logging.getLogger(__name__)

PROBE_TOOL_NAME = "probe_echo"
PROBE_MAX_TOKENS = 4096
PROBE_THINKING_BUDGET = 1024
PROBE_TURN1_INSTRUCTION = (
    "先思考，然后调用 probe_echo 工具，参数 text=ok。不要用文字回答。"
)
PROBE_TURN2_INSTRUCTION = "工具已返回，请用一句话总结。"

_PROBE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def _verdict(turn: int, ok: bool, detail: str, skipped: bool = False) -> dict:
    return {
        "turn": turn,
        "ok": ok,
        "skipped": skipped,
        "detail": detail,
    }


def _headers(api_key: str, protocol: str) -> dict[str, str]:
    if protocol == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    return {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }


async def _post(
    http_client: httpx.AsyncClient,
    api_key: str,
    body: dict,
    protocol: str,
) -> tuple[int, object]:
    endpoint = "/v1/messages" if protocol == "anthropic" else "/v1/chat/completions"
    response = await http_client.post(
        f"{settings.litellm_url}{endpoint}",
        headers=_headers(api_key, protocol),
        json=body,
    )
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text


def _error_detail(status: int, payload: object) -> str:
    text = (
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    )
    mapped = map_error(status_code=status, response_text=text)
    return mapped.get("title") or f"HTTP {status}"


def _is_thinking_unsupported(payload: object) -> bool:
    text = (
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    ).lower()
    return "thinking" in text and (
        "not support" in text
        or "unsupported" in text
        or "does not support" in text
        or "invalid" in text
    )


def _build_turn1_body(model: str, protocol: str) -> dict:
    if protocol == "anthropic":
        return {
            "model": model,
            "max_tokens": PROBE_MAX_TOKENS,
            "thinking": {
                "type": "enabled",
                "budget_tokens": PROBE_THINKING_BUDGET,
            },
            "tools": [
                {
                    "name": PROBE_TOOL_NAME,
                    "description": "回显文本，仅用于接入探针",
                    "input_schema": _PROBE_TOOL_SCHEMA,
                }
            ],
            "messages": [{"role": "user", "content": PROBE_TURN1_INSTRUCTION}],
        }
    return {
        "model": model,
        "max_tokens": PROBE_MAX_TOKENS,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": PROBE_TOOL_NAME,
                    "description": "回显文本，仅用于接入探针",
                    "parameters": _PROBE_TOOL_SCHEMA,
                },
            }
        ],
        "messages": [{"role": "user", "content": PROBE_TURN1_INSTRUCTION}],
    }


def _anthropic_turn2(model: str, payload: dict, tools: list) -> tuple[dict, bool, str]:
    content = payload.get("content") or []
    tool_id = next(
        (block.get("id") for block in content if block.get("type") == "tool_use"),
        None,
    )
    messages: list[dict] = [
        {"role": "user", "content": PROBE_TURN1_INSTRUCTION},
        {"role": "assistant", "content": content},
    ]
    if tool_id:
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": "ok",
                    },
                    {"type": "text", "text": PROBE_TURN2_INSTRUCTION},
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": PROBE_TURN2_INSTRUCTION})
    has_thinking = any(
        block.get("type") in {"thinking", "redacted_thinking"} for block in content
    )
    detail = "返回 thinking 块" if has_thinking else "未返回 thinking 块"
    detail += " + tool_use 块" if tool_id else "（无 tool_use）"
    body = {
        "model": model,
        "max_tokens": PROBE_MAX_TOKENS,
        "thinking": {"type": "enabled", "budget_tokens": PROBE_THINKING_BUDGET},
        "tools": tools,
        "messages": messages,
    }
    return body, bool(tool_id), detail


def _openai_turn2(model: str, payload: dict) -> tuple[dict, bool, str]:
    choices = payload.get("choices") or []
    message = (choices[0].get("message") if choices else {}) or {}
    tool_calls = message.get("tool_calls") or []
    assistant_message: dict = {"role": "assistant", "content": message.get("content")}
    if tool_calls:
        assistant_message["tool_calls"] = tool_calls
    messages: list[dict] = [
        {"role": "user", "content": PROBE_TURN1_INSTRUCTION},
        assistant_message,
    ]
    for call in tool_calls:
        messages.append(
            {"role": "tool", "tool_call_id": call.get("id"), "content": "ok"}
        )
    messages.append({"role": "user", "content": PROBE_TURN2_INSTRUCTION})
    detail = "返回 tool_calls" if tool_calls else "未返回 tool_calls（回放文本历史）"
    body = {
        "model": model,
        "max_tokens": PROBE_MAX_TOKENS,
        "messages": messages,
    }
    return body, bool(tool_calls), detail


async def _run_turn1(
    http_client: httpx.AsyncClient,
    model: str,
    api_key: str,
    protocol: str,
) -> tuple[dict | None, dict]:
    """Run turn 1; return (payload, verdict). payload is None on failure/skip."""
    body = _build_turn1_body(model, protocol)
    try:
        status, payload = await _post(http_client, api_key, body, protocol)
    except Exception as exc:
        logger.error("history probe turn1 error (%s): %s", model, str(exc))
        return None, _verdict(1, False, f"探针请求异常：{exc}")
    if status != 200:
        if protocol == "anthropic" and _is_thinking_unsupported(payload):
            return None, _verdict(
                1, True, "模型不支持 thinking 参数，跳过", skipped=True
            )
        return None, _verdict(
            1, False, f"探针请求失败：{_error_detail(status, payload)}"
        )
    if not isinstance(payload, dict):
        return None, _verdict(1, False, "第一轮响应不是 JSON")
    return payload, _verdict(1, True, "")


async def run_history_probe(
    model: str,
    api_key: str,
    protocol: str,
    replay_model: str | None = None,
) -> dict:
    """两轮请求：第一轮生成 thinking/工具调用，第二轮回放历史继续对话。"""
    target_model = replay_model or model
    verdicts: list[dict] = []
    async with httpx.AsyncClient(timeout=120, trust_env=False) as http_client:
        payload, verdict = await _run_turn1(http_client, model, api_key, protocol)
        verdicts.append(verdict)
        if payload is None:
            return _result(protocol, model, target_model, verdicts)

        if protocol == "anthropic":
            tools = _build_turn1_body(model, protocol)["tools"]
            turn2_body, has_tool, detail = _anthropic_turn2(
                target_model, payload, tools
            )
        else:
            turn2_body, has_tool, detail = _openai_turn2(target_model, payload)
        verdicts[0] = _verdict(1, True, detail)

        try:
            status, payload = await _post(http_client, api_key, turn2_body, protocol)
        except Exception as exc:
            logger.error("history probe turn2 error (%s): %s", target_model, str(exc))
            verdicts.append(_verdict(2, False, f"探针请求异常：{exc}"))
            return _result(protocol, model, target_model, verdicts)

        if status == 200:
            verdicts.append(
                _verdict(
                    2,
                    True,
                    f"历史回放通过（thinking + {'工具结果' if has_tool else '文本'}）",
                )
            )
        elif "signature" in json.dumps(payload, ensure_ascii=False).lower():
            verdicts.append(
                _verdict(2, False, "历史回放签名校验失败（疑似切换模型后签名失效）")
            )
        else:
            verdicts.append(
                _verdict(2, False, f"历史回放失败：{_error_detail(status, payload)}")
            )

    return _result(protocol, model, target_model, verdicts)


def _result(protocol: str, model: str, replay_model: str, verdicts: list[dict]) -> dict:
    return {
        "success": all(v["ok"] for v in verdicts),
        "protocol": protocol,
        "model": model,
        "replay_model": replay_model,
        "verdicts": verdicts,
    }
