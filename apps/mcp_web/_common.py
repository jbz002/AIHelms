"""用户自助 MCP 工具共享：错误映射、分页输入、actor 身份、序列化。"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from exceptions import ConflictError, NotFoundError, ValidationError


class PageInput(BaseModel):
    """分页输入基类。"""

    model_config = {"str_strip_whitespace": True}

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量，1-100")


def error_text(e: Exception) -> str:
    """把 service 抛的业务异常映射成面向调用方的错误文本。"""
    if isinstance(e, NotFoundError):
        return f"错误：{e.resource} 不存在 ({e.identifier})"
    if isinstance(e, ConflictError):
        return f"错误：数据冲突 - {e}"
    if isinstance(e, ValidationError):
        return f"错误：参数错误 - {e}"
    return f"错误：{type(e).__name__} - {e}"


def actor() -> dict:
    """从当前 MCP 请求的 access_token 取 actor 身份。

    必须在工具请求上下文内调用；缺失身份抛 ValidationError。返回
    {user_id, username, api_key_id, is_admin}。
    """
    from fastmcp.server.dependencies import get_access_token

    token = get_access_token()
    if token is None or not token.claims:
        raise ValidationError("MCP 请求缺少用户身份，无法执行操作")
    user_id = token.claims.get("user_id")
    if user_id is None:
        raise ValidationError("MCP 身份缺少 user_id")
    return {
        "user_id": int(user_id),
        "username": token.claims.get("username", ""),
        "api_key_id": token.claims.get("api_key_id"),
        "is_admin": bool(token.claims.get("is_admin", False)),
    }


def actor_id() -> int:
    """从当前 MCP 请求取 actor user_id（按用户过滤数据的依据）。"""
    return actor()["user_id"]


def _default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"not serializable: {type(obj)}")


def json_dumps(data: Any) -> str:
    """统一序列化 service 返回的 data（处理 Decimal/datetime）。"""
    return json.dumps(data, ensure_ascii=False, default=_default, indent=2)
