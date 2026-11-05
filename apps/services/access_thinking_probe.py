"""Thinking 探针：两轮真实请求，校验 thinking 参数与签名在链路上存活。

背景（对齐 cc-switch thinking_rectifier / reasoning_bridge 的经验）：跨方言翻译路径
（anthropic 入口 + openai 凭证裸名组）可能丢 thinking 参数或剥 thinking 签名，导致
多轮思考对话第二轮被上游签名校验拒绝。连通性测试与工具探针均不覆盖此路径。
判定只依赖协议约定：上游接受 thinking 请求则响应应含 thinking 块（带签名），
回放该 thinking 块的多轮请求不应被签名校验拒绝。
"""

import json
import logging

import httpx

from core.config import settings
from services.access_test_error_mapper import map_error

logger = logging.getLogger(__name__)

PROBE_MAX_TOKENS = 4096
PROBE_THINKING_BUDGET = 2048
PROBE_TURN1_INSTRUCTION = "思考后用一句话回答：1+1 等于几。"
PROBE_TURN2_INSTRUCTION = "继续，用一句话回答：2+2 等于几。"

_SIGNATURE_FAIL_DETAIL = "thinking 签名校验失败，多轮思考对话不可用（疑似翻译层剥签名）"
_NO_THINKING_DETAIL = "上游接受 thinking 请求但响应未含 thinking 块"


def _verdict(turn: int, ok: bool, detail: str, skipped: bool = False) -> dict:
    return {
        "turn": turn,
        "mode": "nonstream",
        "ok": ok,
        "skipped": skipped,
        "detail": detail,
    }


def _is_thinking_unsupported(payload: object) -> bool:
    """上游明确拒绝 thinking 参数（非推理模型等），属跳过而非失败。"""
    text = (
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    )
    lowered = text.lower()
    return "thinking" in lowered and (
        "not support" in lowered
        or "unsupported" in lowered
        or "does not support" in lowered
        or "invalid" in lowered
    )


def _extract_thinking_block(payload: dict) -> dict | None:
    for block in payload.get("content") or []:
        if block.get("type") == "thinking":
            return block
    return None


def _extract_text_block(payload: dict) -> dict:
    for block in payload.get("content") or []:
        if block.get("type") == "text":
            return block
    return {"type": "text", "text": ""}


def _anthropic_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


async def _post(
    http_client: httpx.AsyncClient, api_key: str, body: dict
) -> tuple[int, object]:
    response = await http_client.post(
        f"{settings.litellm_url}/v1/messages",
        headers=_anthropic_headers(api_key),
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


async def run_thinking_probe(model: str, api_key: str, protocol: str) -> dict:
    """对目标路由组跑两轮 thinking 探针，聚合判定。

    仅 anthropic 协议有判定力（thinking 块 + 签名是 anthropic 方言语义）；
    openai 协议请求无签名语义，直接跳过。
    """
    verdicts: list[dict] = []
    async with httpx.AsyncClient(timeout=90, trust_env=False) as http_client:
        if protocol != "anthropic":
            return {
                "success": True,
                "protocol": protocol,
                "verdicts": [
                    _verdict(
                        0, True, "openai 协议无 thinking 签名语义，跳过", skipped=True
                    )
                ],
            }

        turn1_body = {
            "model": model,
            "max_tokens": PROBE_MAX_TOKENS,
            "thinking": {"type": "enabled", "budget_tokens": PROBE_THINKING_BUDGET},
            "messages": [{"role": "user", "content": PROBE_TURN1_INSTRUCTION}],
        }
        try:
            status, payload = await _post(http_client, api_key, turn1_body)
        except Exception as e:
            logger.error("thinking probe turn1 error (%s): %s", model, str(e))
            verdicts.append(_verdict(1, False, f"探针请求异常：{e}"))
            return {"success": False, "protocol": protocol, "verdicts": verdicts}

        if status != 200:
            if _is_thinking_unsupported(payload):
                verdicts.append(
                    _verdict(1, True, "模型不支持 thinking 参数，跳过", skipped=True)
                )
            else:
                verdicts.append(
                    _verdict(
                        1, False, f"探针请求失败：{_error_detail(status, payload)}"
                    )
                )
            return {
                "success": all(v["ok"] for v in verdicts),
                "protocol": protocol,
                "verdicts": verdicts,
            }

        thinking_block = (
            _extract_thinking_block(payload) if isinstance(payload, dict) else None
        )
        if not thinking_block:
            verdicts.append(_verdict(1, False, _NO_THINKING_DETAIL))
            return {"success": False, "protocol": protocol, "verdicts": verdicts}
        has_signature = bool(thinking_block.get("signature"))
        verdicts.append(
            _verdict(
                1,
                True,
                "返回 thinking 块" + ("（含签名）" if has_signature else "（无签名，翻译路径合成）"),
            )
        )

        # 无签名（跨方言翻译路径合成）也回放：上游/翻译层可能剥掉 thinking 但链路可用，
        # 判定交给 turn2 实际结果——被拒才失败。

        turn2_body = {
            "model": model,
            "max_tokens": PROBE_MAX_TOKENS,
            "thinking": {"type": "enabled", "budget_tokens": PROBE_THINKING_BUDGET},
            "messages": [
                {"role": "user", "content": PROBE_TURN1_INSTRUCTION},
                {
                    "role": "assistant",
                    "content": [thinking_block, _extract_text_block(payload)],
                },
                {"role": "user", "content": PROBE_TURN2_INSTRUCTION},
            ],
        }
        try:
            status, payload = await _post(http_client, api_key, turn2_body)
        except Exception as e:
            logger.error("thinking probe turn2 error (%s): %s", model, str(e))
            verdicts.append(_verdict(2, False, f"探针请求异常：{e}"))
            return {"success": False, "protocol": protocol, "verdicts": verdicts}

        if status != 200:
            text = (
                payload
                if isinstance(payload, str)
                else json.dumps(payload, ensure_ascii=False)
            )
            if "signature" in text.lower():
                verdicts.append(_verdict(2, False, _SIGNATURE_FAIL_DETAIL))
            else:
                verdicts.append(
                    _verdict(
                        2,
                        False,
                        f"回放 thinking 块失败：{_error_detail(status, payload)}",
                    )
                )
        else:
            verdicts.append(_verdict(2, True, "thinking 块多轮回放通过"))

    return {
        "success": all(v["ok"] for v in verdicts),
        "protocol": protocol,
        "verdicts": verdicts,
    }
