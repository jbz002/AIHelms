"""P2 服务账号与委托授权：令牌生命周期与委托覆盖范围。

不起 DB：仓储层全部 monkeypatch。真实的唯一索引/部分索引由迁移保证，
这里验的是「逻辑对」——尤其是 fail-closed（停用/过期一律拒）。
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from exceptions import ConflictError, ValidationError
from models.db import ServiceAccount
from services import service_account_service as svc


def _sa(**kw) -> ServiceAccount:
    base = dict(
        id=1,
        name="dingtalk-bot",
        kind="bot",
        description="",
        owner_user_id=None,
        token_prefix="sk_sa_deadbeef",
        token_hash="x" * 64,
        status="active",
        expires_at=None,
    )
    base.update(kw)
    return ServiceAccount(**base)


def test_generated_token_shape_and_hash():
    token, prefix, token_hash = svc._generate_token()
    assert token.startswith("sk_sa_")
    assert prefix == token[: len("sk_sa_") + 8]
    assert token.startswith(prefix)
    assert token_hash == svc.hash_token(token)
    # 两次生成不重复
    assert svc._generate_token()[0] != token


@pytest.mark.asyncio
async def test_verify_token_rejects_unknown_prefix(monkeypatch):
    async def boom(session, token_hash):
        raise AssertionError("不该查库")

    monkeypatch.setattr(svc.service_account_repo, "find_by_token_hash", boom)
    assert await svc.verify_token(None, "sk_cli_whatever") is None
    assert await svc.verify_token(None, "") is None


@pytest.mark.asyncio
async def test_verify_token_fail_closed(monkeypatch):
    token, _, token_hash = svc._generate_token()
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)

    async def found(session, th):
        return _sa(token_hash=th, expires_at=expired)

    monkeypatch.setattr(svc.service_account_repo, "find_by_token_hash", found)
    assert await svc.verify_token(None, token) is None  # 过期

    async def disabled(session, th):
        return _sa(token_hash=th, status="disabled")

    monkeypatch.setattr(svc.service_account_repo, "find_by_token_hash", disabled)
    assert await svc.verify_token(None, token) is None  # 停用

    async def ok(session, th):
        return _sa(token_hash=th)

    monkeypatch.setattr(svc.service_account_repo, "find_by_token_hash", ok)
    assert (await svc.verify_token(None, token)) is not None


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name(monkeypatch):
    async def exists(session, name):
        return _sa()

    monkeypatch.setattr(svc.service_account_repo, "find_by_name", exists)
    with pytest.raises(ConflictError):
        await svc.create_service_account(None, name="dingtalk-bot")


@pytest.mark.asyncio
async def test_create_rejects_bad_kind(monkeypatch):
    async def missing(session, name):
        return None

    monkeypatch.setattr(svc.service_account_repo, "find_by_name", missing)
    with pytest.raises(ValidationError):
        await svc.create_service_account(None, name="x", kind="robot")


@pytest.mark.asyncio
async def test_rotate_changes_hash(monkeypatch):
    sa = _sa()
    old_hash = sa.token_hash

    async def get(session, sa_id):
        return sa

    async def flush(session):
        return None

    async def refresh(session, obj):
        return None

    monkeypatch.setattr(svc.service_account_repo, "find_by_id", get)
    # rotate_token 内部直接 flush/refresh 的是传入 session；用替身对象承接
    session = SimpleNamespace(flush=lambda: flush(None), refresh=lambda o: refresh(None, o))
    new_sa, token = await svc.rotate_token(session, 1)
    assert new_sa is sa
    assert sa.token_hash != old_hash
    assert sa.token_hash == svc.hash_token(token)
    assert token.startswith(sa.token_prefix)


@pytest.mark.asyncio
async def test_delegation_allows_server_and_toolset(monkeypatch):
    server_grant = SimpleNamespace(target_type="server", target_id=7)
    toolset_grant = SimpleNamespace(target_type="toolset", target_id=3)

    async def grants_for(session, sa_id, user_id):
        return [toolset_grant]

    async def toolset_by_id(session, tid):
        return SimpleNamespace(
            items=[
                {"server_id": 2, "tool_name": "supplier_search"},
                {"server_id": 2, "tool_name": "supplier_order_search"},
            ]
        )

    monkeypatch.setattr(svc.service_account_repo, "active_delegations_for", grants_for)
    monkeypatch.setattr(svc.mcp_authz_repo, "find_toolset_by_id", toolset_by_id)

    assert await svc.delegation_allows(None, 1, 1, 2, "supplier_search") is True
    assert await svc.delegation_allows(None, 1, 1, 2, "stock_search") is False
    assert await svc.delegation_allows(None, 1, 1, 9, "supplier_search") is False

    async def server_grants(session, sa_id, user_id):
        return [server_grant]

    monkeypatch.setattr(svc.service_account_repo, "active_delegations_for", server_grants)
    assert await svc.delegation_allows(None, 1, 1, 7, "anything") is True
    assert await svc.delegation_allows(None, 1, 1, 8, "anything") is False


@pytest.mark.asyncio
async def test_delegation_allows_without_grants(monkeypatch):
    async def none(session, sa_id, user_id):
        return []

    monkeypatch.setattr(svc.service_account_repo, "active_delegations_for", none)
    assert await svc.delegation_allows(None, 1, 1, 2, "x") is False


@pytest.mark.asyncio
async def test_grant_delegation_rejects_duplicate(monkeypatch):
    async def sa_ok(session, sa_id):
        return _sa()

    async def user_ok(session, user_id):
        return SimpleNamespace(id=user_id)

    async def server_ok(session, server_id):
        return SimpleNamespace(id=server_id)

    async def existing(session, sa_id, user_id, target_type, target_id):
        return SimpleNamespace(id=99)

    monkeypatch.setattr(svc.service_account_repo, "find_by_id", sa_ok)
    monkeypatch.setattr(svc.user_repo, "find_user_by_id", user_ok)
    monkeypatch.setattr(svc.mcp_repo, "find_server_by_id", server_ok)
    monkeypatch.setattr(svc.service_account_repo, "find_active_delegation", existing)

    with pytest.raises(ConflictError):
        await svc.grant_delegation(
            None,
            service_account_id=1,
            user_id=1,
            target_type="server",
            target_id=2,
        )


@pytest.mark.asyncio
async def test_grant_delegation_rejects_past_expiry(monkeypatch):
    async def sa_ok(session, sa_id):
        return _sa()

    async def user_ok(session, user_id):
        return SimpleNamespace(id=user_id)

    async def server_ok(session, server_id):
        return SimpleNamespace(id=server_id)

    async def missing(session, sa_id, user_id, target_type, target_id):
        return None

    monkeypatch.setattr(svc.service_account_repo, "find_by_id", sa_ok)
    monkeypatch.setattr(svc.user_repo, "find_user_by_id", user_ok)
    monkeypatch.setattr(svc.mcp_repo, "find_server_by_id", server_ok)
    monkeypatch.setattr(svc.service_account_repo, "find_active_delegation", missing)

    with pytest.raises(ValidationError):
        await svc.grant_delegation(
            None,
            service_account_id=1,
            user_id=1,
            target_type="server",
            target_id=2,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
