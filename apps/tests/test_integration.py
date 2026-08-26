"""AI Hub 服务间集成（RFC 7523 JWT Bearer Assertion）测试（依赖 dev 中间件真实 DB+Redis 不可用走 fake）。

- 验签链：RS256 签名 / iss / aud / exp / iat 容差 / 寿命上限 / jti 防重放
- 算法混淆（HS256 拿公钥当 HMAC 密钥）必须被拒
- 用户映射：已知用户复用本地行，未知用户占位 upsert + provision
- 令牌双向隔离：集成 token 过普通认证被拒；普通 token 过集成解码被拒
- identity 返回 get_my_keys 全量结构并落审计
"""

import asyncio
import time
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwt
from sqlalchemy import delete, select, update

from core.config import settings
from core.database import get_worker_session_factory
from core.security import create_access_token
from exceptions import ForbiddenError, UnauthorizedError
from models.db import AdminAuditLog, AiKey, User
from services import integration_service


def _gen_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return priv_pem, pub_pem


PRIV_MAIN, PUB_MAIN = _gen_keypair()
PRIV_SECOND, PUB_SECOND = _gen_keypair()
PRIV_WRONG, _PUB_WRONG = _gen_keypair()


class _FakeRedis:
    """手写 redis stub：仅实现 service 用到的 set(nx)/incr/expire。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return key in self.counters


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(integration_service, "get_redis", lambda: fake)
    return fake


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


def _configure(monkeypatch, *, public_keys: str | None = None) -> None:
    monkeypatch.setattr(settings, "aihub_integration_enabled", True)
    monkeypatch.setattr(
        settings, "aihub_integration_public_keys", public_keys or PUB_MAIN
    )
    monkeypatch.setattr(settings, "aihub_integration_iss", "aihub")
    monkeypatch.setattr(settings, "aihub_integration_aud", "aihelms")
    monkeypatch.setattr(settings, "aihub_integration_token_expire_minutes", 30)
    monkeypatch.setattr(settings, "aihub_integration_max_assertion_seconds", 300)
    monkeypatch.setattr(settings, "aihub_integration_iat_leeway_seconds", 60)
    monkeypatch.setattr(settings, "aihub_integration_rate_limit_per_minute", 60)
    monkeypatch.setattr(settings, "secret_key", "test-secret-integration")


def _make_assertion(
    overrides: dict | None = None,
    priv: str | None = None,
    sub: str = "aihub-int-test-uid",
) -> str:
    now = int(time.time())
    claims: dict = {
        "iss": "aihub",
        "aud": "aihelms",
        "sub": sub,
        "jti": uuid4().hex,
        "iat": now,
        "exp": now + 120,
    }
    claims.update(overrides or {})
    return jwt.encode(claims, priv or PRIV_MAIN, algorithm="RS256")


@pytest.mark.asyncio
async def test_valid_assertion_issues_token_with_integration_use(monkeypatch):
    _configure(monkeypatch)
    session = _session()
    try:
        data = await integration_service.issue_integration_token(
            session, _make_assertion()
        )
    finally:
        await session.close()

    assert data["token_type"] == "Bearer"
    assert data["expires_in"] == 30 * 60
    payload = jwt.decode(
        data["access_token"], settings.secret_key, algorithms=["HS256"]
    )
    assert payload["token_use"] == "integration"
    assert payload["aihub_user_id"] == "aihub-int-test-uid"
    assert payload["sub"]  # 本地 user_id


@pytest.mark.asyncio
async def test_known_user_reuses_local_row(monkeypatch):
    _configure(monkeypatch)
    session = _session()
    try:
        user = await integration_service._upsert_integration_user(
            session, "aihub-int-test-known"
        )
        known_id = user.id
        data = await integration_service.issue_integration_token(
            session, _make_assertion(sub="aihub-int-test-known")
        )
    finally:
        await session.close()

    payload = jwt.decode(
        data["access_token"], settings.secret_key, algorithms=["HS256"]
    )
    assert payload["sub"] == str(known_id)

    async with _session() as s:
        rows = (
            (
                await s.execute(
                    select(User).where(User.aihub_user_id == "aihub-int-test-known")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_unknown_user_upserts_placeholder_and_provisions(
    monkeypatch, _stub_provision
):
    _configure(monkeypatch)
    session = _session()
    try:
        await integration_service.issue_integration_token(
            session, _make_assertion(sub="aihub-int-test-newcomer")
        )
    finally:
        await session.close()

    assert _stub_provision.await_count == 1

    async with _session() as s:
        user = (
            await s.execute(
                select(User).where(User.aihub_user_id == "aihub-int-test-newcomer")
            )
        ).scalar_one_or_none()
        assert user is not None
        assert user.username == "aihub_aihub-in"
        assert user.email == "aihub-int-test-newcomer@aihub.local"


@pytest.mark.asyncio
async def test_inactive_user_rejected(monkeypatch):
    _configure(monkeypatch)
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
            await integration_service.issue_integration_token(
                session, _make_assertion(sub="aihub-int-test-off")
            )
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_wrong_signature_rejected(monkeypatch):
    _configure(monkeypatch)
    assertion = _make_assertion(priv=PRIV_WRONG)
    session = _session()
    try:
        with pytest.raises(UnauthorizedError, match="断言无效"):
            await integration_service.issue_integration_token(session, assertion)
    finally:
        await session.close()


def _hs256_confusion_token(claims: dict, hmac_secret: str) -> str:
    """手工构造 alg=HS256 的 JWT（绕开 jose 对 PEM 做 HMAC 的防护），模拟真实攻击者。"""
    import base64
    import hashlib
    import hmac as hmac_mod
    import json

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = b64url(
        hmac_mod.new(hmac_secret.encode(), signing_input, hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


@pytest.mark.asyncio
async def test_hs256_algorithm_confusion_rejected(monkeypatch):
    """攻击者拿我方公钥 PEM 当 HS256 密钥签名，必须被 RS256 算法白名单拒绝。"""
    _configure(monkeypatch)
    now = int(time.time())
    claims = {
        "iss": "aihub",
        "aud": "aihelms",
        "sub": "aihub-int-test-uid",
        "jti": uuid4().hex,
        "iat": now,
        "exp": now + 120,
    }
    assertion = _hs256_confusion_token(claims, PUB_MAIN)
    session = _session()
    try:
        with pytest.raises(UnauthorizedError, match="断言无效"):
            await integration_service.issue_integration_token(session, assertion)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_expired_assertion_rejected(monkeypatch):
    _configure(monkeypatch)
    now = int(time.time())
    assertion = _make_assertion({"iat": now - 300, "exp": now - 60})
    session = _session()
    try:
        with pytest.raises(UnauthorizedError, match="断言无效"):
            await integration_service.issue_integration_token(session, assertion)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_wrong_iss_rejected(monkeypatch):
    _configure(monkeypatch)
    assertion = _make_assertion({"iss": "someone-else"})
    session = _session()
    try:
        with pytest.raises(UnauthorizedError, match="断言无效"):
            await integration_service.issue_integration_token(session, assertion)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_wrong_aud_rejected(monkeypatch):
    _configure(monkeypatch)
    assertion = _make_assertion({"aud": "not-aihelms"})
    session = _session()
    try:
        with pytest.raises(UnauthorizedError, match="断言无效"):
            await integration_service.issue_integration_token(session, assertion)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_future_iat_beyond_leeway_rejected(monkeypatch):
    _configure(monkeypatch)
    now = int(time.time())
    assertion = _make_assertion({"iat": now + 120, "exp": now + 240})
    session = _session()
    try:
        with pytest.raises(UnauthorizedError, match="断言无效"):
            await integration_service.issue_integration_token(session, assertion)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_overlong_assertion_lifetime_rejected(monkeypatch):
    _configure(monkeypatch)
    now = int(time.time())
    assertion = _make_assertion({"iat": now, "exp": now + 600})
    session = _session()
    try:
        with pytest.raises(UnauthorizedError, match="断言无效"):
            await integration_service.issue_integration_token(session, assertion)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_jti_replay_rejected(monkeypatch, _fake_redis):
    _configure(monkeypatch)
    assertion = _make_assertion(sub="aihub-int-test-replay")
    session = _session()
    try:
        await integration_service.issue_integration_token(session, assertion)
        with pytest.raises(UnauthorizedError, match="断言无效"):
            await integration_service.issue_integration_token(session, assertion)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_token_isolation_both_directions(monkeypatch):
    _configure(monkeypatch)
    session = _session()
    try:
        data = await integration_service.issue_integration_token(
            session, _make_assertion()
        )
    finally:
        await session.close()

    # 集成 token 调普通认证接口：被拒
    with pytest.raises(HTTPException) as exc_info:
        from core.deps import _authenticate_jwt

        _authenticate_jwt(data["access_token"])
    assert exc_info.value.status_code == 401

    # 普通登录 token（无 token_use）过集成解码：被拒
    normal_token = create_access_token({"sub": "1", "username": "normal-user"})
    with pytest.raises(UnauthorizedError):
        integration_service.decode_integration_token(normal_token)


@pytest.mark.asyncio
async def test_identity_returns_full_key_structure_and_audits(monkeypatch):
    _configure(monkeypatch)
    # 捕获 fire-and-forget 审计 task 并显式 await：asyncpg 连接绑 event loop，
    # 测试结束 loop 销毁若 task 未完，滞留连接会污染下一测试（InterfaceError）
    spawned: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def _capture_create_task(coro):
        task = real_create_task(coro)
        spawned.append(task)
        return task

    monkeypatch.setattr(integration_service.asyncio, "create_task", _capture_create_task)

    session = _session()
    try:
        data = await integration_service.issue_integration_token(
            session, _make_assertion(sub="aihub-int-test-identity")
        )
        identity = integration_service.decode_integration_token(data["access_token"])

        # 手动放一条个人主 key（绕开 litellm 真实调用）
        session.add(
            AiKey(
                name="integration-test-key",
                key_type="personal_main",
                owner_type="user",
                owner_id=identity["user_id"],
                litellm_key_id="sk-int-test-plaintext",
                is_active=True,
            )
        )
        await session.commit()

        result = await integration_service.get_integration_identity_data(
            session, identity, ip="test-ip-integration"
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


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_threshold(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "aihub_integration_rate_limit_per_minute", 2)
    await integration_service.check_token_endpoint_rate_limit("1.2.3.4")
    await integration_service.check_token_endpoint_rate_limit("1.2.3.4")
    with pytest.raises(ForbiddenError, match="请求过于频繁"):
        await integration_service.check_token_endpoint_rate_limit("1.2.3.4")


@pytest.mark.asyncio
async def test_disabled_integration_forbidden(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "aihub_integration_enabled", False)
    session = _session()
    try:
        with pytest.raises(ForbiddenError, match="集成通道未启用"):
            await integration_service.issue_integration_token(
                session, _make_assertion()
            )
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_secondary_public_key_verifies(monkeypatch):
    """轮换期：两把公钥同时登记，第二把私钥签的断言可通过。"""
    _configure(monkeypatch, public_keys=PUB_MAIN + PUB_SECOND)
    assertion = _make_assertion(priv=PRIV_SECOND)
    session = _session()
    try:
        data = await integration_service.issue_integration_token(session, assertion)
        assert data["access_token"]
    finally:
        await session.close()
