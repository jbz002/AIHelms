"""P3 · AI Hub OAuth2 SSO 登录链路测试（依赖 dev 中间件真实 DB）。

- oauth2_login: code → AI Hub /token + /me app_roles → upsert 本地用户 → 签本地 JWT
- is_admin 由 app_roles 含 ai_hub_admin_role 映射（SSO 唯一管理员判定链路）
- code 无效（AI Hub /token 非 200）抛 UnauthorizedError
- upsert 幂等：同 aihub_user_id 二次登录复用本地行
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt
from sqlalchemy import delete, select

from core.config import settings
from core.database import get_worker_session_factory
from core.security import ALGORITHM
from exceptions import UnauthorizedError
from models.db import Department, User
from services import auth_service


@pytest.fixture(autouse=True)
def _stub_provision(monkeypatch):
    """provision_user_resources 会调 litellm 真实服务，测试环境 noop stub 隔离。"""
    monkeypatch.setattr(
        "services.auth_service.user_service.provision_user_resources",
        AsyncMock(),
    )


def _session():
    return get_worker_session_factory()()


def _mock_aihub_client(
    *,
    token_status: int = 200,
    app_roles: list[str] | None = None,
    aihub_user: dict | None = None,
) -> AsyncMock:
    """构造 mock httpx.AsyncClient，/token + /me 响应可控。"""
    post_resp = MagicMock()
    post_resp.status_code = token_status
    post_resp.json.return_value = {
        "access_token": "aihub-token-xxx",
        "user": aihub_user
        or {
            "id": "aihub-uid-sso-test",
            "username": "sso_test_user",
            "email": "sso_test@aihub.local",
            "real_name": "SSO Test",
            "department_id": None,
        },
    }
    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.json.return_value = {"app_roles": app_roles or []}

    client = AsyncMock()
    client.post = AsyncMock(return_value=post_resp)
    client.get = AsyncMock(return_value=get_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _configure_sso(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_hub_url", "http://test-aihub")
    monkeypatch.setattr(settings, "ai_hub_app_code", "aihelms")
    monkeypatch.setattr(settings, "ai_hub_admin_role", "aihelms-admin")
    monkeypatch.setattr(settings, "secret_key", "test-secret-sso")


async def _cleanup_aihub_user(aihub_user_id: str) -> None:
    async with _session() as s:
        await s.execute(delete(User).where(User.aihub_user_id == aihub_user_id))
        await s.commit()


@pytest.mark.asyncio
async def test_oauth2_login_admin_role_maps_is_admin_true(monkeypatch):
    _configure_sso(monkeypatch)
    client = _mock_aihub_client(app_roles=["aihelms-admin"])
    with patch("services.auth_service.httpx.AsyncClient", return_value=client):
        session = _session()
        try:
            token, _user = await auth_service.oauth2_login(session, "fake-code")
        finally:
            await session.close()

    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    assert payload["is_admin"] is True
    assert payload["aihub_user_id"] == "aihub-uid-sso-test"
    assert payload["app_roles"] == ["aihelms-admin"]
    assert payload["username"] == "sso_test_user"

    await _cleanup_aihub_user("aihub-uid-sso-test")


@pytest.mark.asyncio
async def test_oauth2_login_no_role_maps_is_admin_false(monkeypatch):
    _configure_sso(monkeypatch)
    client = _mock_aihub_client(app_roles=[])
    with patch("services.auth_service.httpx.AsyncClient", return_value=client):
        session = _session()
        try:
            token, _user = await auth_service.oauth2_login(session, "fake-code")
        finally:
            await session.close()

    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    assert payload["is_admin"] is False
    assert payload["app_roles"] == []

    await _cleanup_aihub_user("aihub-uid-sso-test")


@pytest.mark.asyncio
async def test_oauth2_login_invalid_code_raises_unauthorized(monkeypatch):
    _configure_sso(monkeypatch)
    client = _mock_aihub_client(token_status=401)
    with patch("services.auth_service.httpx.AsyncClient", return_value=client):
        session = _session()
        try:
            with pytest.raises(UnauthorizedError):
                await auth_service.oauth2_login(session, "bad-code")
        finally:
            await session.close()


@pytest.mark.asyncio
async def test_oauth2_login_upsert_idempotent_reuses_local_user(monkeypatch):
    _configure_sso(monkeypatch)
    aihub_user = {
        "id": "aihub-uid-idem",
        "username": "sso_idem_user",
        "email": "sso_idem@aihub.local",
        "real_name": "SSO Idem",
        "department_id": None,
    }
    client = _mock_aihub_client(app_roles=["aihelms-admin"], aihub_user=aihub_user)
    with patch("services.auth_service.httpx.AsyncClient", return_value=client):
        session1 = _session()
        try:
            _token1, user1 = await auth_service.oauth2_login(session1, "code-1")
        finally:
            await session1.close()

        session2 = _session()
        try:
            _token2, user2 = await auth_service.oauth2_login(session2, "code-2")
        finally:
            await session2.close()

    assert user1.id == user2.id

    await _cleanup_aihub_user("aihub-uid-idem")


def _mock_aihub_ticket_client(
    *,
    verify_status: int = 200,
    app_roles: list[str] | None = None,
    aihub_user: dict | None = None,
) -> AsyncMock:
    """构造 mock httpx.AsyncClient，verify-ticket 响应可控（直接返 user dict）。"""
    post_resp = MagicMock()
    post_resp.status_code = verify_status
    post_resp.json.return_value = aihub_user or {
        "id": "aihub-uid-ticket-test",
        "username": "ticket_test_user",
        "email": "ticket_test@aihub.local",
        "real_name": "Ticket Test",
        "department_id": None,
        "app_roles": app_roles or [],
    }
    client = AsyncMock()
    client.post = AsyncMock(return_value=post_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_ticket_login_admin_role_maps_is_admin_true(monkeypatch):
    _configure_sso(monkeypatch)
    client = _mock_aihub_ticket_client(app_roles=["aihelms-admin"])
    with patch("services.auth_service.httpx.AsyncClient", return_value=client):
        session = _session()
        try:
            token, _user = await auth_service.ticket_login(session, "fake-ticket")
        finally:
            await session.close()

    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    assert payload["is_admin"] is True
    assert payload["aihub_user_id"] == "aihub-uid-ticket-test"
    assert payload["app_roles"] == ["aihelms-admin"]

    await _cleanup_aihub_user("aihub-uid-ticket-test")


@pytest.mark.asyncio
async def test_ticket_login_invalid_ticket_raises_unauthorized(monkeypatch):
    _configure_sso(monkeypatch)
    client = _mock_aihub_ticket_client(verify_status=401)
    with patch("services.auth_service.httpx.AsyncClient", return_value=client):
        session = _session()
        try:
            with pytest.raises(UnauthorizedError):
                await auth_service.ticket_login(session, "bad-ticket")
        finally:
            await session.close()


def _mock_aihub_client_with_dept(
    *, dept_id: str, dept_name: str, app_roles: list[str] | None = None
) -> AsyncMock:
    """mock httpx.AsyncClient：/me 返回 app_roles+department_id，/departments/{id} 返回 name。"""
    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.json.return_value = {
        "access_token": "aihub-token-dept",
        "user": {
            "id": "aihub-uid-dept-test",
            "username": "sso_dept_user",
            "email": "sso_dept@aihub.local",
            "real_name": "Dept Test",
            "department_id": dept_id,
        },
    }

    def _get(url, params=None, headers=None):  # type: ignore[no-untyped-def]
        resp = MagicMock()
        resp.status_code = 200
        if "/api/v1/auth/me" in url:
            resp.json.return_value = {
                "app_roles": app_roles or [],
                "department_id": dept_id,
            }
        elif "/api/v1/departments/" in url:
            resp.json.return_value = {"name": dept_name, "code": "test-dept"}
        else:
            resp.json.return_value = {}
        return resp

    client = AsyncMock()
    client.post = AsyncMock(return_value=post_resp)
    client.get = AsyncMock(side_effect=_get)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


async def _cleanup_dept_sync(aihub_user_id: str, aihub_dept_id: str) -> None:
    async with _session() as s:
        await s.execute(delete(User).where(User.aihub_user_id == aihub_user_id))
        await s.execute(
            delete(Department).where(Department.aihub_department_id == aihub_dept_id)
        )
        await s.commit()


@pytest.mark.asyncio
async def test_oauth2_login_syncs_department_to_local(monkeypatch):
    """SSO 登录带 department_id 时，同步建本地部门 + 关联，/me 返回非空 departments。"""
    _configure_sso(monkeypatch)
    dept_id = "aihub-dept-sync-test"
    dept_name = "SSO测试部"
    client = _mock_aihub_client_with_dept(dept_id=dept_id, dept_name=dept_name)
    with patch("services.auth_service.httpx.AsyncClient", return_value=client):
        session = _session()
        try:
            _token, user = await auth_service.oauth2_login(session, "code-dept")
        finally:
            await session.close()

    # /me 在生产是新请求新 session，用独立 session 验证关系加载
    async with _session() as me_session:
        info = await auth_service.get_current_user_info(me_session, user.id)

    assert len(info["departments"]) == 1
    assert info["departments"][0]["name"] == dept_name
    assert isinstance(info["departments"][0]["id"], int)

    async with _session() as s:
        dept = (
            await s.execute(
                select(Department).where(Department.aihub_department_id == dept_id)
            )
        ).scalar_one_or_none()
        assert dept is not None and dept.name == dept_name

    await _cleanup_dept_sync("aihub-uid-dept-test", dept_id)


@pytest.mark.asyncio
async def test_oauth2_login_without_department_creates_no_dept_row(monkeypatch):
    """aihub_user 无 department_id 时，不建本地部门、/me departments 为空。"""
    _configure_sso(monkeypatch)
    client = _mock_aihub_client(app_roles=[])  # aihub_user.department_id = None
    with patch("services.auth_service.httpx.AsyncClient", return_value=client):
        session = _session()
        try:
            _token, user = await auth_service.oauth2_login(session, "code-no-dept")
        finally:
            await session.close()

    async with _session() as me_session:
        info = await auth_service.get_current_user_info(me_session, user.id)

    assert info["departments"] == []

    await _cleanup_aihub_user("aihub-uid-sso-test")
