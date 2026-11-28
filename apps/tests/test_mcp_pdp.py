"""P2 PDP：差量策略判定与原因码。

不起 DB：仓储与用户授权全部 monkeypatch。重点验 fail-closed 的几条：
机器自身无授权、server 未开机器委托、委托过期/缺失、工具未过审。
"""

from types import SimpleNamespace

import pytest

from services import mcp_pdp


def _server(**kw):
    base = dict(
        id=2,
        server_name="supply_cloud",
        is_published=True,
        requires_approval=False,
        sync_to_litellm=True,
        is_public=False,
        allow_machine_delegation=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _tool(**kw):
    base = dict(
        tool_name="supplier_search",
        tool_key="supply_cloud.supplier_search",
        is_active=True,
        review_status="approved",
        risk_level="read",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _env(
    monkeypatch,
    *,
    server=None,
    tools=None,
    authorized=(),
    limits=None,
    machine_ok=True,
    has_expired=False,
):
    async def find_server(session, name):
        if server is False:  # 约定：False = server 不存在
            return None
        return _server() if server is None else server

    async def find_tools(session, server_id):
        return list(tools if tools is not None else [_tool()])

    async def user_authz(session, user_id):
        return set(authorized), dict(limits or {})

    async def delegation(session, sa_id, user_id, server_id, tool_name):
        return machine_ok

    async def any_delegation(session, sa_id, user_id, *, server_id, tool_name):
        return SimpleNamespace(id=1) if has_expired else None

    async def policy_version(session):
        return 11

    monkeypatch.setattr(mcp_pdp.mcp_repo, "find_server_by_name", find_server)
    monkeypatch.setattr(mcp_pdp.mcp_repo, "find_tools_by_server", find_tools)
    monkeypatch.setattr(mcp_pdp, "_user_authorization", user_authz)
    monkeypatch.setattr(
        mcp_pdp.service_account_service, "delegation_allows", delegation
    )
    monkeypatch.setattr(mcp_pdp.service_account_repo, "find_any_delegation", any_delegation)
    monkeypatch.setattr(mcp_pdp.mcp_authz_repo, "current_policy_version", policy_version)
    mcp_pdp.clear_cache()


async def _decide(monkeypatch, **kw):
    params = dict(
        subject_type="user",
        subject_id=1,
        actor_kind="human",
        actor_service_account_id=None,
        server_name="supply_cloud",
        tool_name="supplier_search",
        policy_version=11,
    )
    params.update(kw)
    return await mcp_pdp._decide(None, **params)


@pytest.mark.asyncio
async def test_server_offline(monkeypatch):
    _env(monkeypatch, server=False)
    d = await _decide(monkeypatch)
    assert (d.decision, d.reason_code) == ("deny", mcp_pdp.R_SERVER_OFFLINE)


@pytest.mark.asyncio
async def test_unpublished_or_catalog_only(monkeypatch):
    for kw in (
        {"is_published": False},
        {"requires_approval": True},
        {"sync_to_litellm": False},
    ):
        _env(monkeypatch, server=_server(**kw))
        d = await _decide(monkeypatch)
        assert d.reason_code == mcp_pdp.R_SERVER_OFFLINE, kw


@pytest.mark.asyncio
async def test_tool_not_found_and_not_approved(monkeypatch):
    _env(monkeypatch, tools=[])
    assert (await _decide(monkeypatch)).reason_code == mcp_pdp.R_TOOL_NOT_FOUND

    _env(monkeypatch, tools=[_tool(review_status="pending")])
    d = await _decide(monkeypatch)
    assert d.reason_code == mcp_pdp.R_TOOL_NOT_APPROVED
    assert d.tool_key == "supply_cloud.supplier_search"


@pytest.mark.asyncio
async def test_no_grant_and_tool_limit(monkeypatch):
    _env(monkeypatch, authorized=())
    assert (await _decide(monkeypatch)).reason_code == mcp_pdp.R_NO_GRANT

    # 有 server 级授权但被工具级限制排除
    _env(monkeypatch, authorized=(2,), limits={2: ["supplier_order_search"]})
    assert (await _decide(monkeypatch)).reason_code == mcp_pdp.R_NO_GRANT


@pytest.mark.asyncio
async def test_human_allowed(monkeypatch):
    _env(monkeypatch, authorized=(2,))
    d = await _decide(monkeypatch)
    assert (d.decision, d.reason_code) == ("allow", mcp_pdp.R_GRANTED)
    assert d.policy_version == 11
    assert d.obligations == {"requires_approval": False}

    _env(monkeypatch, server=_server(is_public=True), authorized=(2,))
    d = await _decide(monkeypatch)
    assert (d.decision, d.reason_code) == ("allow", mcp_pdp.R_PUBLIC_SERVER)


@pytest.mark.asyncio
async def test_machine_needs_server_switch(monkeypatch):
    _env(monkeypatch, authorized=(2,), machine_ok=True)
    d = await _decide(monkeypatch, actor_kind="service", actor_service_account_id=5)
    assert d.reason_code == mcp_pdp.R_MACHINE_NOT_ALLOWED


@pytest.mark.asyncio
async def test_machine_delegation_reasons(monkeypatch):
    server = _server(allow_machine_delegation=True)

    _env(monkeypatch, server=server, authorized=(2,), machine_ok=True)
    d = await _decide(monkeypatch, actor_kind="service", actor_service_account_id=5)
    assert (d.decision, d.reason_code) == ("allow", mcp_pdp.R_GRANTED)

    _env(monkeypatch, server=server, authorized=(2,), machine_ok=False)
    d = await _decide(monkeypatch, actor_kind="service", actor_service_account_id=5)
    assert d.reason_code == mcp_pdp.R_DELEGATION_MISSING

    _env(
        monkeypatch, server=server, authorized=(2,), machine_ok=False, has_expired=True
    )
    d = await _decide(monkeypatch, actor_kind="service", actor_service_account_id=5)
    assert d.reason_code == mcp_pdp.R_DELEGATION_EXPIRED

    # 服务账号身份缺失（actor=service 但没带 sa_id）
    _env(monkeypatch, server=server, authorized=(2,))
    d = await _decide(monkeypatch, actor_kind="service", actor_service_account_id=None)
    assert d.reason_code == mcp_pdp.R_MACHINE_SELF


@pytest.mark.asyncio
async def test_machine_self_denied(monkeypatch):
    _env(monkeypatch, authorized=(2,))
    d = await _decide(monkeypatch, subject_id=None, actor_kind="service")
    assert d.reason_code == mcp_pdp.R_MACHINE_SELF


@pytest.mark.asyncio
async def test_anonymous_human_denied(monkeypatch):
    _env(monkeypatch, authorized=(2,))
    d = await _decide(monkeypatch, subject_type="anonymous", subject_id=None)
    assert d.reason_code == mcp_pdp.R_NO_GRANT


@pytest.mark.asyncio
async def test_authorize_caches_within_policy_version(monkeypatch):
    _env(monkeypatch, authorized=(2,))
    first = await mcp_pdp.authorize(
        None,
        subject_type="user",
        subject_id=1,
        actor_kind="human",
        server_name="supply_cloud",
        tool_name="supplier_search",
        log=False,
    )
    second = await mcp_pdp.authorize(
        None,
        subject_type="user",
        subject_id=1,
        actor_kind="human",
        server_name="supply_cloud",
        tool_name="supplier_search",
        log=False,
    )
    assert first.cached is False
    assert second.cached is True
    assert second.decision == "allow"

    # 策略版本变了 → 缓存自然失效
    async def bumped(session):
        return 12

    monkeypatch.setattr(mcp_pdp.mcp_authz_repo, "current_policy_version", bumped)
    third = await mcp_pdp.authorize(
        None,
        subject_type="user",
        subject_id=1,
        actor_kind="human",
        server_name="supply_cloud",
        tool_name="supplier_search",
        log=False,
    )
    assert third.cached is False
