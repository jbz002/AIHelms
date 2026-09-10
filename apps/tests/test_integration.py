"""AI Hub 服务间集成（方式七自省验证）测试（依赖 dev 中间件真实 DB 不可用部分走 stub）。

- 自省链：Bearer 缺失 / introspect 401 / valid=false / AI Hub 不可达 / ai_hub_url 未配置被拒
- 透传正确性：Bearer 原样转发、app_code/target_path/method 参数
- 路由层：caller_type=app 拒（个人数据须用户态）、user_id 缺失拒
- 用户映射：已知用户复用本地行，未知用户占位 upsert + provision，禁用用户拒
- identity 返回 get_my_keys 全量结构并落审计
"""

import asyncio

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from starlette.requests import Request

from core.config import settings
from core.database import get_worker_session_factory
from exceptions import UnauthorizedError
from models.db import AdminAuditLog, AiKey, User
from services import integration_service

UID = "aihub-int-test-uid"
PATH = "/api/v1/integration/identity"
TOKEN = "ey-test-access-token"


def _make_request(
    *,
    method: str = "GET",
    path: str = PATH,
    authorization: str | None = f"Bearer {TOKEN}",
) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": (
            [(b"authorization", authorization.encode())]
            if authorization is not None
            else []
        ),
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _stub_introspect(monkeypatch, *, status_code: int = 200, body: dict | None = None):
    """替换 core.aihub_verify._introspect，记录调用参数并返回固定响应。"""
    calls: list[dict] = []

    async def fake(
        authorization: str, target_path: str, method: str
    ) -> tuple[int, dict]:
        calls.append(
            {
                "authorization": authorization,
                "target_path": target_path,
                "method": method,
            }
        )
        return status_code, body if body is not None else {"valid": True}

    monkeypatch.setattr("core.aihub_verify._introspect", fake)
    return calls


def _user_body(user_id: str = UID) -> dict:
    return {
        "valid": True,
        "caller_type": "user",
        "user_id": user_id,
        "username": "tester",
        "app_code": "aihelms",
        "app_roles": [],
    }


async def _verify(request: Request) -> dict:
    from core.aihub_verify import verify_aihub_credential

    return await verify_aihub_credential(request)


@pytest.fixture(autouse=True)
def _stub_provision(monkeypatch):
    """provision_user_resources 会调 litellm 真实服务，测试环境 AsyncMock 隔离。"""
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    monkeypatch.setattr(
        "services.integration_service.user_service.provision_user_resources", mock
    )
    return mock


@pytest.fixture(autouse=True)
def _configure_aihub(monkeypatch):
    monkeypatch.setattr(settings, "ai_hub_url", "http://aihub-test:30080")
    monkeypatch.setattr(settings, "ai_hub_app_code", "aihelms")


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    await _cleanup_all()
    # 审计写库走全局池 engine（非 NullPool），连接绑当前测试 loop；
    # 不 dispose 则旧 loop 连接滞留池中，污染后续跨文件测试（InterfaceError）
    from core.database import engine

    await engine.dispose()


def _session():
    return get_worker_session_factory()()


async def _cleanup_all() -> None:
    async with _session() as s:
        test_user_ids = (
            (
                await s.execute(
                    select(User.id).where(User.aihub_user_id.like("aihub-int-test%"))
                )
            )
            .scalars()
            .all()
        )
        if test_user_ids:
            await s.execute(delete(AiKey).where(AiKey.owner_id.in_(test_user_ids)))
        await s.execute(delete(User).where(User.aihub_user_id.like("aihub-int-test%")))
        await s.execute(
            delete(AdminAuditLog).where(AdminAuditLog.ip == "test-ip-integration")
        )
        await s.commit()


# --- 自省鉴权链 ---


@pytest.mark.asyncio
async def test_valid_credential_passes_through(monkeypatch):
    calls = _stub_introspect(monkeypatch, body=_user_body())
    caller = await _verify(_make_request())
    assert caller["caller_type"] == "user"
    assert caller["user_id"] == UID
    # Bearer 原样透传 + 自省参数正确
    assert calls[0]["authorization"] == f"Bearer {TOKEN}"
    assert calls[0]["target_path"] == PATH
    assert calls[0]["method"] == "GET"


@pytest.mark.asyncio
async def test_missing_bearer_rejected(monkeypatch):
    calls = _stub_introspect(monkeypatch)
    with pytest.raises(HTTPException) as exc_info:
        await _verify(_make_request(authorization=None))
    assert exc_info.value.status_code == 401
    assert calls == []  # 未打到 AI Hub


@pytest.mark.asyncio
async def test_non_bearer_scheme_rejected(monkeypatch):
    calls = _stub_introspect(monkeypatch)
    with pytest.raises(HTTPException) as exc_info:
        await _verify(_make_request(authorization="Basic dXNlcjpwYXNz"))
    assert exc_info.value.status_code == 401
    assert calls == []


@pytest.mark.asyncio
async def test_introspect_401_rejected(monkeypatch):
    _stub_introspect(monkeypatch, status_code=401, body={"detail": "凭证无效"})
    with pytest.raises(HTTPException) as exc_info:
        await _verify(_make_request())
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_introspect_valid_false_rejected(monkeypatch):
    _stub_introspect(monkeypatch, body={"valid": False})
    with pytest.raises(HTTPException) as exc_info:
        await _verify(_make_request())
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_introspect_unreachable_fail_closed(monkeypatch):
    async def unreachable(authorization: str, target_path: str, method: str):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("core.aihub_verify._introspect", unreachable)
    with pytest.raises(HTTPException) as exc_info:
        await _verify(_make_request())
    assert exc_info.value.status_code == 401
    assert "不可用" in exc_info.value.detail


@pytest.mark.asyncio
async def test_aihub_url_not_configured_rejected(monkeypatch):
    monkeypatch.setattr(settings, "ai_hub_url", "")
    with pytest.raises(HTTPException) as exc_info:
        await _verify(_make_request())
    assert exc_info.value.status_code == 401
    assert "未配置" in exc_info.value.detail


# --- 路由层 ---


@pytest.mark.asyncio
async def test_app_caller_forbidden_on_identity(monkeypatch):
    """caller_type=app 是服务态，个人身份须用户态凭证（防服务态查任意用户）。"""
    _stub_introspect(
        monkeypatch,
        body={
            "valid": True,
            "caller_type": "app",
            "app_code": "ai-chat",
            "app_roles": [],
        },
    )
    from api.v1.integration import get_integration_identity_keys

    with pytest.raises(HTTPException) as exc_info:
        await get_integration_identity_keys(
            request=_make_request(),
            caller=await _verify(_make_request()),
            session=_session(),
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_user_id_in_credential_rejected(monkeypatch):
    _stub_introspect(monkeypatch, body={"valid": True, "caller_type": "user"})
    from api.v1.integration import get_integration_identity_keys

    with pytest.raises(HTTPException) as exc_info:
        await get_integration_identity_keys(
            request=_make_request(),
            caller=await _verify(_make_request()),
            session=_session(),
        )
    assert exc_info.value.status_code == 401


# --- 用户映射与 identity 数据（service 层） ---


def _mk_user(aihub_uid: str, *, is_active: bool = True) -> dict:
    return {
        "aihub_user_id": aihub_uid,
        "username": f"u_{aihub_uid}",
        "email": f"{aihub_uid}@test.local",
        "display_name": "集成测试",
        "is_active": is_active,
    }


async def _seed_user(aihub_uid: str, *, is_active: bool = True) -> int:
    async with _session() as s:
        user = User(
            username=f"u_{aihub_uid}",
            email=f"{aihub_uid}@test.local",
            display_name="集成测试",
            hashed_password="!",
            is_active=is_active,
            aihub_user_id=aihub_uid,
        )
        s.add(user)
        await s.commit()
        return user.id


@pytest.mark.asyncio
async def test_unknown_user_upserts_placeholder_and_provisions(_stub_provision):
    async with _session() as session:
        user = await integration_service.get_user_by_aihub_id(session, UID)
        assert user.id is not None
        assert user.aihub_user_id == UID
        assert _stub_provision.await_count == 1
        await session.commit()


@pytest.mark.asyncio
async def test_known_user_reused_without_provision(_stub_provision):
    await _seed_user(UID)
    async with _session() as session:
        user = await integration_service.get_user_by_aihub_id(session, UID)
        assert user.aihub_user_id == UID
        assert _stub_provision.await_count == 0


@pytest.mark.asyncio
async def test_disabled_user_rejected():
    await _seed_user(UID, is_active=False)
    async with _session() as session:
        with pytest.raises(UnauthorizedError):
            await integration_service.get_integration_identity_data(
                session, UID, ip="test-ip-integration"
            )


@pytest.mark.asyncio
async def test_identity_returns_key_groups_and_audits(_stub_provision, monkeypatch):
    """全量结构返回（空用户三组为空列表）+ 审计落行且无 key 明文。"""
    await _seed_user(UID)
    async with _session() as session:
        data = await integration_service.get_integration_identity_data(
            session, UID, ip="test-ip-integration"
        )
        assert set(data.keys()) == {"personal", "department", "project"}
        assert all(isinstance(v, list) for v in data.values())

    for _ in range(10):
        async with _session() as s:
            result = await s.execute(
                select(AdminAuditLog).where(AdminAuditLog.ip == "test-ip-integration")
            )
            log = result.scalars().first()
        if log:
            break
        await asyncio.sleep(0.2)
    assert log is not None
    assert log.identity_type == "integration"
    assert log.action == "集成拉取用户 AI 身份"
    assert log.detail["aihub_user_id"] == UID
    assert "litellm_key_id" not in str(log.detail)
