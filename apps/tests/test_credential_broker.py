"""P2-F4 Token Broker：换票、缓存、失败码。

不起 DB / Redis / 真网络：Redis 用内存 fake，AI Hub 与全域认证中心用
httpx.MockTransport。重点验三件事——失败收敛成稳定码、缓存不重复换票、
票不因异常路径泄漏（这里用「审计字段里没有票」间接表达）。
"""

from contextlib import asynccontextmanager

import httpx
import pytest

from core.config import settings
from services import credential_broker as cb

AIHUB_USER = "69f2ad48fdcb2baa290629c2"


# ─── 测试替身 ───────────────────────────────────────────────────────────────


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttls[key] = ex or 0
        return True

    async def delete(self, key):
        self.ttls.pop(key, None)
        return 1 if self.store.pop(key, None) is not None else 0


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()

    monkeypatch.setattr(cb, "get_redis", lambda: fake)

    @asynccontextmanager
    async def _lock(key, ttl=None):
        yield

    monkeypatch.setattr(cb, "redis_lock", _lock)

    monkeypatch.setattr(settings, "mcp_credential_broker_enabled", True)
    monkeypatch.setattr(settings, "quanyu_auth_url", "http://quanyu.test")
    monkeypatch.setattr(settings, "quanyu_app_id", "app-aihelms")
    monkeypatch.setattr(settings, "quanyu_app_secret", "secret-not-logged")
    monkeypatch.setattr(settings, "quanyu_target_app_id", "scp")
    monkeypatch.setattr(settings, "quanyu_target_app_ids", "supply_cloud:scp,product_order:pop")
    monkeypatch.setattr(settings, "ai_hub_url", "http://aihub.test")
    monkeypatch.setattr(settings, "ai_hub_app_key", "ak-test")
    monkeypatch.setattr(settings, "quanyu_token_refresh_margin_seconds", 60)
    return fake


def _wire_http(monkeypatch, *, user=None, user_status=None, exchange=None):
    """把 httpx.AsyncClient 换到 MockTransport：按路径分发两个上游。

    注意 ``cb.httpx`` 就是 httpx 模块本身，同一测试里只能调一次（会叠加）。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/v1/common/users/" in str(request.url):
            if user_status is not None:
                return httpx.Response(user_status, json={})
            if user is None:
                return httpx.Response(404, json={"detail": "not found"})
            return httpx.Response(200, json=user)
        if str(request.url).endswith("/aiIdentity/exchange"):
            return exchange(request)
        return httpx.Response(500, json={"unexpected": str(request.url)})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(cb.httpx, "AsyncClient", factory)


def _ok_exchange(expires_in=300, token="delegation-token-value"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"code": 200, "data": {"token": token, "expiresIn": expires_in}}
        )

    return handler


# ─── 目标解析 ───────────────────────────────────────────────────────────────


def test_target_mapping_is_whitelist(fake_redis):
    assert cb.target_app_for("supply_cloud") == "scp"
    assert cb.target_app_for("product_order") == "pop"
    # 映射存在时未命中一律空串（docs 检索这类不需要全域身份）
    assert cb.target_app_for("docs_mcp_server") == ""


def test_target_falls_back_to_single_app(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "quanyu_target_app_ids", "")
    assert cb.target_app_for("anything") == "scp"


# ─── 失败码 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_target_denies_without_upstream(fake_redis, monkeypatch):
    called = []

    def handler(request):
        called.append(str(request.url))
        return httpx.Response(500)

    _wire_http(monkeypatch, exchange=handler)

    result = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="docs_mcp_server"
    )

    assert result.ok is False
    assert result.reason_code == cb.R_TARGET_UNKNOWN
    assert called == []


@pytest.mark.asyncio
async def test_unconfigured_provider_denies(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "quanyu_app_secret", "")

    result = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )

    assert result.reason_code == cb.R_PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_user_without_dingtalk_identity_is_not_bound(fake_redis, monkeypatch):
    _wire_http(monkeypatch, user={"id": AIHUB_USER, "username": "someone"})

    result = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )

    assert result.ok is False
    assert result.reason_code == cb.R_SUBJECT_NOT_BOUND


@pytest.mark.asyncio
async def test_aihub_5xx_is_provider_unavailable(fake_redis, monkeypatch):
    # 404 才是 not_bound；5xx 属于提供方不可用
    _wire_http(monkeypatch, user_status=502)

    result = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )

    assert result.reason_code == cb.R_PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_exchange_rejected_with_bind_message_is_not_bound(fake_redis, monkeypatch):
    _wire_http(
        monkeypatch,
        user={"dingtalk_union_id": "union-1"},
        exchange=lambda r: httpx.Response(
            200, json={"code": 400, "msg": "该用户未绑定全域账号"}
        ),
    )

    result = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )

    assert result.reason_code == cb.R_SUBJECT_NOT_BOUND


@pytest.mark.asyncio
async def test_exchange_rejected_other_message_is_provider_unavailable(
    fake_redis, monkeypatch
):
    _wire_http(
        monkeypatch,
        user={"dingtalk_union_id": "union-1"},
        exchange=lambda r: httpx.Response(200, json={"code": 500, "msg": "系统繁忙"}),
    )

    result = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )

    assert result.reason_code == cb.R_PROVIDER_UNAVAILABLE


# ─── 正常路径与缓存 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exchange_returns_header_and_token(fake_redis, monkeypatch):
    _wire_http(monkeypatch, user={"dingtalk_union_id": "union-1"}, exchange=_ok_exchange())

    result = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )

    assert result.ok is True
    assert result.reason_code == cb.R_EXCHANGED
    assert result.header == cb.DELEGATION_HEADER == "X-AI-Delegation"
    assert result.token == "delegation-token-value"
    assert result.expires_in == 300
    assert result.cached is False


@pytest.mark.asyncio
async def test_second_call_hits_cache_and_skips_upstream(fake_redis, monkeypatch):
    hits = {"exchange": 0}

    def handler(request):
        hits["exchange"] += 1
        return httpx.Response(200, json={"code": 200, "data": {"token": "t1", "expiresIn": 300}})

    _wire_http(monkeypatch, user={"dingtalk_union_id": "union-1"}, exchange=handler)

    first = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )
    second = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )

    assert first.cached is False and second.cached is True
    assert hits["exchange"] == 1
    # TTL = expires_in − margin
    key = cb._cache_key("aihub_user", AIHUB_USER, "supply_cloud", "human")
    assert fake_redis.ttls[key] == 240


@pytest.mark.asyncio
async def test_invalidate_forces_new_exchange(fake_redis, monkeypatch):
    hits = {"exchange": 0}

    def handler(request):
        hits["exchange"] += 1
        return httpx.Response(200, json={"code": 200, "data": {"token": "t1", "expiresIn": 300}})

    _wire_http(monkeypatch, user={"dingtalk_union_id": "union-1"}, exchange=handler)

    await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )
    deleted = await cb.invalidate(
        subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )
    again = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )

    assert deleted is True
    assert again.cached is False
    assert hits["exchange"] == 2


@pytest.mark.asyncio
async def test_cache_failure_degrades_to_direct_exchange(fake_redis, monkeypatch):
    class BrokenRedis:
        async def get(self, key):
            raise RuntimeError("redis down")

        async def set(self, key, value, ex=None):
            raise RuntimeError("redis down")

    monkeypatch.setattr(cb, "get_redis", lambda: BrokenRedis())
    _wire_http(monkeypatch, user={"dingtalk_union_id": "union-1"}, exchange=_ok_exchange())

    result = await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )

    assert result.ok is True
    assert result.cached is False


@pytest.mark.asyncio
async def test_actor_kind_changes_cache_bucket(fake_redis, monkeypatch):
    hits = {"exchange": 0}

    def handler(request):
        hits["exchange"] += 1
        return httpx.Response(200, json={"code": 200, "data": {"token": "t", "expiresIn": 300}})

    _wire_http(monkeypatch, user={"dingtalk_union_id": "union-1"}, exchange=handler)

    await cb.exchange(
        None, subject_type="aihub_user", subject_id=AIHUB_USER, target="supply_cloud"
    )
    await cb.exchange(
        None,
        subject_type="aihub_user",
        subject_id=AIHUB_USER,
        target="supply_cloud",
        actor_kind="service",
    )

    assert hits["exchange"] == 2  # 人类票与机器票不共用
