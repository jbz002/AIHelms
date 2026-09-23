"""跨应用兼容鉴权（get_current_user_compat）测试——skill 浏览器面方式六接入。

- 通道顺序：平台 API Key 前缀短路 → 自有 JWT 本地验签 → AI Hub introspect
- introspect user 态：按 AI Hub user_id 定位/占位建档，identity 字段按本地用户派生
- introspect 拒（401/valid=false）/ app 态 / 无 Authorization 的失败语义
- skills.py 浏览器面五端点（published/market-detail/card/summary/full）接线断言
"""

import inspect

import pytest
from fastapi import HTTPException
from jose import jwt
from sqlalchemy import delete, select
from starlette.requests import Request

from core.config import settings
from core.database import engine, get_worker_session_factory
from core.deps import get_current_user_compat
from core.security import ALGORITHM
from models.db import AiKey, User

UID = "aihub-int-test-compat-uid"
TOKEN = "ey-aihub-access-token"

# ── 自有 JWT（本地验签通道，不落库）────────────────────────────


def _local_token(**extra) -> str:
    return jwt.encode(
        {"sub": "42", "username": "local-user", "is_admin": False, **extra},
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def _make_request(authorization: str | None = f"Bearer {TOKEN}") -> Request:
    path = "/api/v1/skills/published"
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": (
            [(b"authorization", authorization.encode())] if authorization else []
        ),
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
    }
    return Request(scope, receive)


async def receive():
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.fixture(autouse=True)
def _configure_aihub(monkeypatch):
    monkeypatch.setattr(settings, "ai_hub_url", "http://aihub-test:30080")
    monkeypatch.setattr(settings, "ai_hub_app_code", "aihelms")


@pytest.fixture(autouse=True)
def _stub_provision(monkeypatch):
    """provision_user_resources 会调 litellm 真实服务，测试环境 AsyncMock 隔离。"""
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    monkeypatch.setattr(
        "services.integration_service.user_service.provision_user_resources", mock
    )
    return mock


def _stub_introspect(monkeypatch, *, status_code: int = 200, body: dict | None = None):
    async def fake(authorization, target_path, method):
        return status_code, body if body is not None else {"valid": True}

    monkeypatch.setattr("core.aihub_verify._introspect", fake)


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    async with get_worker_session_factory()() as s:
        ids = (
            (await s.execute(select(User.id).where(User.aihub_user_id == UID)))
            .scalars()
            .all()
        )
        if ids:
            await s.execute(delete(AiKey).where(AiKey.owner_id.in_(ids)))
        await s.execute(delete(User).where(User.aihub_user_id == UID))
        await s.commit()
    # 连接绑当前测试 loop，不 dispose 则污染后续跨文件测试（同 test_integration）
    await engine.dispose()


async def _compat(request: Request) -> dict:
    """直调依赖函数（绕过 FastAPI 注入），session 手动供给。"""
    async with get_worker_session_factory()() as session:
        return await get_current_user_compat(request, session)


# ── 通道一/二：平台 Key 短路与自有 JWT ─────────────────────────


@pytest.mark.asyncio
async def test_local_jwt_short_circuits_without_introspect(monkeypatch):
    """自有 JWT 本地验签通过时不触发 introspect（零额外 RTT）。"""
    called = []

    async def fail_fast(*a, **kw):
        called.append(True)
        raise AssertionError("introspect should not be called")

    monkeypatch.setattr("core.aihub_verify._introspect", fail_fast)
    identity = await _compat(_make_request(f"Bearer {_local_token()}"))
    assert identity["id"] == 42
    assert identity["identity_type"] == "user"
    assert called == []


@pytest.mark.asyncio
async def test_missing_authorization_rejected():
    with pytest.raises(HTTPException) as ei:
        await _compat(_make_request(None))
    assert ei.value.status_code == 401


# ── 通道三：AI Hub introspect（方式六）─────────────────────────


@pytest.mark.asyncio
async def test_aihub_user_token_resolves_local_identity(monkeypatch):
    """AI Hub 用户凭证：introspect user 态 → 定位/占位建档 → 本地 identity。"""
    _stub_introspect(
        monkeypatch,
        body={
            "valid": True,
            "caller_type": "user",
            "user_id": UID,
            "username": "tester",
            "app_code": "aihelms",
            "app_roles": [],
        },
    )
    identity = await _compat(_make_request())
    assert identity["identity_type"] == "user"
    assert identity["username"].startswith("aihub_") or identity["username"]
    assert isinstance(identity["id"], int)
    assert isinstance(identity["is_admin"], bool)
    assert isinstance(identity["permissions"], list)


@pytest.mark.asyncio
async def test_aihub_rejection_falls_back_and_fails_closed(monkeypatch):
    """AI Hub 拒（401）且非本站 token → 401 fail-closed。"""
    _stub_introspect(monkeypatch, status_code=401, body={"valid": False})
    with pytest.raises(HTTPException) as ei:
        await _compat(_make_request())
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_aihub_unreachable_fails_closed(monkeypatch):
    """AI Hub 不可达（introspect 抛 httpx 错）→ 401，不泄漏堆栈。"""
    import httpx

    async def boom(authorization, target_path, method):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("core.aihub_verify._introspect", boom)
    with pytest.raises(HTTPException) as ei:
        await _compat(_make_request())
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_aihub_app_caller_rejected(monkeypatch):
    """caller_type=app（服务态）打个人浏览面 → 403。"""
    _stub_introspect(
        monkeypatch,
        body={"valid": True, "caller_type": "app", "app_code": "ai-hub"},
    )
    with pytest.raises(HTTPException) as ei:
        await _compat(_make_request())
    assert ei.value.status_code == 403


# ── skills.py 浏览器面接线 ─────────────────────────────────────


def _dep_name(func, param: str) -> str | None:
    params = inspect.signature(func).parameters
    if param not in params:
        return None
    dependency = getattr(params[param].default, "dependency", None)
    return getattr(dependency, "__name__", None)


def test_browser_face_endpoints_use_compat_dependency():
    """五个用户浏览端点必须挂 get_current_user_compat（防回退纯本站鉴权）。"""
    from api.v1 import skills

    for func in (
        skills.list_published_skills,
        skills.get_skill_market_detail,
        skills.get_skill_card,
        skills.get_skill_summary,
        skills.get_skill_full,
    ):
        names = {
            _dep_name(func, p)
            for p in ("current_user", "_")
            if _dep_name(func, p) is not None
        }
        assert names == {"get_current_user_compat"}, func.__name__


def test_admin_endpoints_keep_strict_dependency():
    """管理面不放松：list_categories 仍走 require_permission（skill:read），非 compat。"""
    from api.v1 import skills

    assert _dep_name(skills.list_categories, "_") != "get_current_user_compat"
