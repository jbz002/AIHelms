"""用户自助 MCP 写工具审计落库。

MCP 全走单端点 POST /web-mcp/mcp 的 JSON-RPC，父 app AuditLogMiddleware 看到的
path 恒相同、无 route.summary，无法区分调用了哪个工具。故由 audited_tool 在工具内
显式落 admin_audit_logs，action 文案由 TOOL_ACTIONS 按 tool_name 映射。
"""

import asyncio
import functools
import json
import logging
import time
from typing import Any, Awaitable, Callable

from core.audit import SENSITIVE_KEYS
from core.database import async_session
from mcp_web._common import actor
from models.db import AdminAuditLog

logger = logging.getLogger(__name__)

REQUEST_SUMMARY_MAX = 4000

# tool_name -> 中文 action 文案（写工具落审计用；只读工具不落库）
TOOL_ACTIONS: dict[str, str] = {
    "web_apply_resource": "申请资源",
}


def audited_tool(
    tool_name: str,
) -> Callable[[Callable[..., Awaitable[str]]], Callable[..., Awaitable[str]]]:
    """写工具审计装饰器，包在 @mcp.tool 内层。

    记录调用耗时与成败状态，异步落 admin_audit_logs。actor 取自请求 access_token；
    审计失败仅告警，不影响业务结果。返回值以「错误」开头视为业务失败（status 400），
    抛异常视为服务器错误（status 500）。
    """

    def decorator(
        fn: Callable[..., Awaitable[str]],
    ) -> Callable[..., Awaitable[str]]:
        @functools.wraps(fn)
        async def wrapper(params: Any) -> str:
            start = time.monotonic()
            actor_info = _safe_actor()
            status_code = 200
            try:
                result = await fn(params)
                if isinstance(result, str) and result.startswith("错误"):
                    status_code = 400
                return result
            except Exception:
                status_code = 500
                raise
            finally:
                duration_ms = int((time.monotonic() - start) * 1000)
                asyncio.create_task(
                    _write_audit(
                        actor_info=actor_info,
                        tool_name=tool_name,
                        status_code=status_code,
                        request_summary=_summarize(params),
                        duration_ms=duration_ms,
                    )
                )

        return wrapper

    return decorator


def _safe_actor() -> dict:
    try:
        return actor()
    except Exception:  # noqa: BLE001
        return {"user_id": 0, "username": "", "api_key_id": None}


def _summarize(params: Any) -> str:
    try:
        dumped = params.model_dump()
    except Exception:  # noqa: BLE001
        return "<non-serializable params>"
    try:
        return json.dumps(_redact(dumped), ensure_ascii=False, default=str)[
            :REQUEST_SUMMARY_MAX
        ]
    except Exception:  # noqa: BLE001
        return "<non-serializable params>"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in SENSITIVE_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


async def _write_audit(
    *,
    actor_info: dict,
    tool_name: str,
    status_code: int,
    request_summary: str,
    duration_ms: int,
) -> None:
    action = TOOL_ACTIONS.get(tool_name, tool_name)
    try:
        async with async_session() as session:
            session.add(
                AdminAuditLog(
                    user_id=actor_info["user_id"],
                    username=actor_info["username"],
                    identity_type="api_key",
                    method="POST",
                    path=f"/web-mcp/mcp#{tool_name}",
                    action=action,
                    status_code=status_code,
                    ip="",
                    user_agent="mcp-client",
                    duration_ms=duration_ms,
                    request_summary=request_summary,
                    request_id="",
                    detail={
                        "tool": tool_name,
                        "api_key_id": actor_info.get("api_key_id"),
                    },
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("mcp audit write failed: tool=%s", tool_name, exc_info=True)
