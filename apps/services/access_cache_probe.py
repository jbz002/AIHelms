"""Prompt Cache 探针：两轮同前缀请求，校验缓存断点在链路上存活。

背景（对齐 cc-switch / Claude Code 成本经验）：客户端重度依赖 cache_control 断点，
翻译层若丢弃断点或改写前缀，成本会放大一个量级。平台已有 cache_read 计费字段，
但从未验证链路是否真的命中缓存。

判定只依赖用量字段：第二轮响应的 cache_read 类 token > 0。
上游不返回缓存字段时判为跳过（供应商不支持或未达最小缓存长度），不误判失败。
"""

import json
import logging

import httpx

from core.config import settings
from services.access_test_error_mapper import map_error

logger = logging.getLogger(__name__)

PROBE_MAX_TOKENS = 16
PROBE_INSTRUCTION = "只回复 OK。"
# 约 3.6k tokens：高于 Anthropic(1024) 与 OpenAI(1024) 的最小缓存长度
PROBE_CACHE_PREFIX = (
    "The following stable prefix exists only to verify prompt caching on the gateway. "
    * 220
)

_CACHE_READ_FIELDS = (
    "cache_read_input_tokens",
    "prompt_cache_hit_tokens",
    "cached_tokens",
)


def _anthropic_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def _openai_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }


def _build_body(model: str, protocol: str) -> dict:
    if protocol == "anthropic":
        return {
            "model": model,
            "max_tokens": PROBE_MAX_TOKENS,
            "system": [
                {
                    "type": "text",
                    "text": PROBE_CACHE_PREFIX,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": PROBE_INSTRUCTION}],
        }
    return {
        "model": model,
        "max_tokens": PROBE_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": PROBE_CACHE_PREFIX},
            {"role": "user", "content": PROBE_INSTRUCTION},
        ],
    }


async def _post(
    http_client: httpx.AsyncClient,
    api_key: str,
    body: dict,
    protocol: str,
) -> tuple[int, object]:
    endpoint = "/v1/messages" if protocol == "anthropic" else "/v1/chat/completions"
    headers = (
        _anthropic_headers(api_key)
        if protocol == "anthropic"
        else _openai_headers(api_key)
    )
    response = await http_client.post(
        f"{settings.litellm_url}{endpoint}", headers=headers, json=body
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


def _usage(payload: dict) -> dict:
    usage = payload.get("usage")
    if isinstance(usage, dict):
        return usage
    choices = payload.get("choices") or []
    if choices and isinstance(choices[0], dict):
        usage = choices[0].get("usage")
        if isinstance(usage, dict):
            return usage
    return {}


def _cache_read_tokens(usage: dict) -> int:
    for field in _CACHE_READ_FIELDS:
        value = usage.get(field)
        if isinstance(value, int):
            return value
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        value = details.get("cached_tokens")
        if isinstance(value, int):
            return value
    return 0


def _has_cache_metrics(usage: dict) -> bool:
    if any(field in usage for field in _CACHE_READ_FIELDS):
        return True
    if "cache_creation_input_tokens" in usage:
        return True
    details = usage.get("prompt_tokens_details")
    return isinstance(details, dict) and "cached_tokens" in details


async def run_cache_probe(model: str, api_key: str, protocol: str) -> dict:
    verdicts: list[dict] = []
    body = _build_body(model, protocol)
    async with httpx.AsyncClient(timeout=120, trust_env=False) as http_client:
        usages: list[dict] = []
        for turn in (1, 2):
            try:
                status, payload = await _post(http_client, api_key, body, protocol)
            except Exception as exc:
                logger.error("cache probe turn%s error (%s): %s", turn, model, str(exc))
                verdicts.append(_verdict(turn, False, f"探针请求异常：{exc}"))
                return _result(model, protocol, verdicts)
            if status != 200 or not isinstance(payload, dict):
                verdicts.append(
                    _verdict(
                        turn, False, f"探针请求失败：{_error_detail(status, payload)}"
                    )
                )
                return _result(model, protocol, verdicts)
            usage = _usage(payload)
            usages.append(usage)
            read_tokens = _cache_read_tokens(usage)
            if turn == 1:
                verdicts.append(
                    _verdict(1, True, f"首轮完成（cache_read={read_tokens}）")
                )
            elif read_tokens > 0:
                verdicts.append(
                    _verdict(2, True, f"缓存命中（cache_read={read_tokens}）")
                )
            elif not _has_cache_metrics(usage) and not _has_cache_metrics(usages[0]):
                verdicts.append(
                    _verdict(
                        2,
                        True,
                        "上游未返回缓存用量字段，无法判定（按跳过处理）",
                        skipped=True,
                    )
                )
            else:
                verdicts.append(
                    _verdict(
                        2,
                        False,
                        "第二轮 cache_read=0，缓存断点未命中（可能供应商不支持或被翻译层丢弃）",
                    )
                )

    return _result(model, protocol, verdicts)


def _verdict(turn: int, ok: bool, detail: str, skipped: bool = False) -> dict:
    return {"turn": turn, "ok": ok, "skipped": skipped, "detail": detail}


def _result(model: str, protocol: str, verdicts: list[dict]) -> dict:
    return {
        "success": all(v["ok"] for v in verdicts),
        "model": model,
        "protocol": protocol,
        "verdicts": verdicts,
    }
