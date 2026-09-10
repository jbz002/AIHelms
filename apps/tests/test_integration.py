"""AI Hub 服务间集成（方式六 HMAC 验签）测试（依赖 dev 中间件真实 DB 不可用部分走 stub）。

- 验签链：时间戳存在/±300s 容差 / 签名串各字段（v1/时间戳/METHOD/path/query/body hash/on_behalf_of）任一篡改被拒
- 签名头缺失 / 非 ASCII / 错密钥 / 密钥未配置被拒
- 用户映射：已知用户复用本地行，未知用户占位 upsert + provision，禁用用户拒
- identity 返回 get_my_keys 全量结构并落审计
"""

import asyncio
import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from starlette.requests import Request

from core.config import settings
from core.database import get_worker_session_factory
from exceptions import UnauthorizedError
from models.db import AdminAuditLog, AiKey, User
from services import integration_service

SECRET_MAIN = "sk-conn-test-main-secret"
SECRET_WRONG = "sk-conn-test-wrong-secret"

PATH = "/api/v1/integration/identity"


def _sign(
    secret: str,
    ts: str,
    method: str,
    path_with_query: str,
    body: bytes = b"",
    on_behalf_of: str | None = None,
) -> str:
    """测试侧按协议同构拼签名串（与 core/aihub_verify 验签算法互为镜像）。"""
    message = "\n".join(
        [
            "v1",
            ts,
            method.upper(),
            path_with_query,
            hashlib.sha256(body or b"").hexdigest(),
            on_behalf_of or "",
        ]
    ).encode()
    return "v1=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _make_request(
    *,
    method: str = "GET",
    path: str = PATH,
    query: str = "",
    body: bytes = b"",
    on_behalf_of: str | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    """构造按协议签好名的请求；headers 中的同名头可覆盖默认值（用于篡改用例）。"""
    ts = str(int(time.time()))
    path_with_query = path + ("?" + query if query else "")
    final_headers: dict[str, str] = {
        "x-aihub-timestamp": ts,
        "x-aihub-signature": _sign(
            SECRET_MAIN, ts, method, path_with_query, body, on_behalf_of
        ),
        **(headers or {}),
    }
    if on_behalf_of is not None:
        final_headers.setdefault("x-aihub-on-behalf-of", on_behalf_of)
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": (path + ("?" + query if query else "")).encode("ascii"),
        "query_string": query.encode("ascii"),
        "headers": [(k.encode(), v.encode()) for k, v in final_headers.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


async def _verify(request: Request) -> str | None:
    from core.aihub_verify import verify_aihub

    return await verify_aihub(request)


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
def _configure_secret(monkeypatch):
    monkeypatch.setattr(settings, "aihub_integration_hmac_secret", SECRET_MAIN)


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


# --- 验签链 ---


@pytest.mark.asyncio
async def test_valid_signature_with_on_behalf_of():
    request = _make_request(on_behalf_of="aihub-int-test-uid")
    assert await _verify(request) == "aihub-int-test-uid"


@pytest.mark.asyncio
async def test_valid_signature_without_on_behalf_of_returns_none():
    request = _make_request()
    assert await _verify(request) is None


@pytest.mark.asyncio
async def test_valid_signature_with_body_and_query():
    request = _make_request(
        method="POST",
        query="a=1&b=%2Fx",
        body=b'{"k": 1}',
        on_behalf_of="aihub-int-test-uid",
    )
    assert await _verify(request) == "aihub-int-test-uid"


@pytest.mark.asyncio
async def test_wrong_secret_rejected():
    ts = str(int(time.time()))
    request = _make_request(
        on_behalf_of="aihub-int-test-uid",
        headers={
            "x-aihub-signature": _sign(
                SECRET_WRONG, ts, "GET", PATH, b"", "aihub-int-test-uid"
            )
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_secret_closes_channel(monkeypatch):
    monkeypatch.setattr(settings, "aihub_integration_hmac_secret", "")
    request = _make_request()
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401
    assert "集成通道未启用" in exc_info.value.detail


@pytest.mark.asyncio
async def test_expired_timestamp_rejected():
    ts = str(int(time.time()) - 301)
    request = _make_request(headers={"x-aihub-timestamp": ts})
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401
    assert "请求已过期" in exc_info.value.detail


@pytest.mark.asyncio
async def test_future_timestamp_beyond_tolerance_rejected():
    request = _make_request(headers={"x-aihub-timestamp": str(int(time.time()) + 301)})
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_or_bad_timestamp_rejected():
    for ts_value in ("", "not-a-number"):
        request = _make_request(headers={"x-aihub-timestamp": ts_value})
        with pytest.raises(HTTPException) as exc_info:
            await _verify(request)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_signature_header_rejected():
    request = _make_request(headers={"x-aihub-signature": ""})
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_non_ascii_signature_rejected():
    """compare_digest 收非 ASCII str 会抛 TypeError（500），必须先校验拦成 401。"""
    request = _make_request(headers={"x-aihub-signature": "v1=签名"})
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_tampered_method_rejected():
    request = _make_request(
        method="POST",
        headers={"x-aihub-signature": _sign(SECRET_MAIN, _ts(), "GET", PATH)},
    )
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_tampered_path_rejected():
    request = _make_request(
        path="/api/v1/integration/other",
        headers={"x-aihub-signature": _sign(SECRET_MAIN, _ts(), "GET", PATH)},
    )
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_tampered_query_rejected():
    request = _make_request(
        query="a=2",
        headers={"x-aihub-signature": _sign(SECRET_MAIN, _ts(), "GET", PATH + "?a=1")},
    )
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_tampered_body_rejected():
    request = _make_request(
        method="POST",
        body=b'{"k": 2}',
        headers={
            "x-aihub-signature": _sign(
                SECRET_MAIN, _ts(), "POST", PATH, body=b'{"k": 1}'
            )
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_tampered_on_behalf_of_rejected():
    request = _make_request(
        on_behalf_of="aihub-int-test-other",
        headers={
            "x-aihub-signature": _sign(
                SECRET_MAIN, _ts(), "GET", PATH, b"", "aihub-int-test-uid"
            )
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        await _verify(request)
    assert exc_info.value.status_code == 401


def _ts() -> str:
    return str(int(time.time()))


# --- 用户定位与身份拉取 ---


@pytest.mark.asyncio
async def test_unknown_user_upserts_placeholder_and_provisions(_stub_provision):
    session = _session()
    try:
        user = await integration_service.get_user_by_aihub_id(
            session, "aihub-int-test-newcomer"
        )
    finally:
        await session.close()

    assert _stub_provision.await_count == 1

    async with _session() as s:
        row = (
            await s.execute(
                select(User).where(User.aihub_user_id == "aihub-int-test-newcomer")
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.id == user.id
        assert row.username == "aihub_aihub-in"
        assert row.email == "aihub-int-test-newcomer@aihub.local"


@pytest.mark.asyncio
async def test_known_user_reuses_local_row(_stub_provision):
    session = _session()
    try:
        first = await integration_service.get_user_by_aihub_id(
            session, "aihub-int-test-known"
        )
        second = await integration_service.get_user_by_aihub_id(
            session, "aihub-int-test-known"
        )
    finally:
        await session.close()

    assert first.id == second.id
    assert _stub_provision.await_count == 1  # 幂等，第二次不再 provision


@pytest.mark.asyncio
async def test_inactive_user_rejected():
    session = _session()
    try:
        await integration_service._upsert_integration_user(
            session, "aihub-int-test-off"
        )
        await session.execute(
            update(User)
            .where(User.aihub_user_id == "aihub-int-test-off")
            .values(is_active=False)
        )
        await session.commit()
        with pytest.raises(UnauthorizedError, match="用户已禁用"):
            await integration_service.get_integration_identity_data(
                session, "aihub-int-test-off", ip="test-ip-integration"
            )
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_identity_returns_full_key_structure_and_audits(monkeypatch):
    # 捕获 fire-and-forget 审计 task 并显式 await：asyncpg 连接绑 event loop，
    # 测试结束 loop 销毁若 task 未完，滞留连接会污染下一测试（InterfaceError）
    spawned: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def _capture_create_task(coro):
        task = real_create_task(coro)
        spawned.append(task)
        return task

    monkeypatch.setattr(
        integration_service.asyncio, "create_task", _capture_create_task
    )

    session = _session()
    try:
        user = await integration_service._upsert_integration_user(
            session, "aihub-int-test-identity"
        )

        # 手动放一条个人主 key（绕开 litellm 真实调用）
        session.add(
            AiKey(
                name="integration-test-key",
                key_type="personal_main",
                owner_type="user",
                owner_id=user.id,
                litellm_key_id="sk-int-test-plaintext",
                is_active=True,
            )
        )
        await session.commit()

        result = await integration_service.get_integration_identity_data(
            session, "aihub-int-test-identity", ip="test-ip-integration"
        )
    finally:
        await session.close()

    for task in spawned:
        await task

    assert set(result.keys()) == {"personal", "department", "project"}
    assert result["personal"][0]["litellm_key_id"] == "sk-int-test-plaintext"

    async with _session() as s:
        audit_row = (
            await s.execute(
                select(AdminAuditLog).where(AdminAuditLog.ip == "test-ip-integration")
            )
        ).scalar_one_or_none()
        assert audit_row is not None
        assert audit_row.identity_type == "integration"
        assert audit_row.detail["aihub_user_id"] == "aihub-int-test-identity"
        assert "sk-int-test-plaintext" not in str(audit_row.detail)


@pytest.mark.asyncio
async def test_router_rejects_missing_on_behalf_of():
    """identity 必须用户维度：on_behalf_of 为 None（服务身份调用）时路由应拒绝。"""
    from api.v1.integration import get_integration_identity_keys

    request = _make_request(headers={"x-forwarded-for": "test-ip-integration"})
    with pytest.raises(HTTPException) as exc_info:
        await get_integration_identity_keys(request, on_behalf_of=None, session=None)
    assert exc_info.value.status_code == 400
