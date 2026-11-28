"""P0 授权收口：object_permission 下发、is_public 公共开关、创建即发布广播。

覆盖的三处缺陷（docs/MCP鉴权增强方案/01 §1.2）：
- key 权限写在 allowed_mcp_servers（网关忽略）→ 改发 object_permission.mcp_servers
- allow_all_keys 无条件 TRUE → 改按 mcp_servers.is_public
- create_server 发布态不广播到存量 key → 补 _sync_mcp_visibility
"""

from types import SimpleNamespace

import pytest

from exceptions import ValidationError
from services import ai_key_service, litellm_client, mcp_service


async def _capture_request(monkeypatch, calls):
    async def fake(method, path, json_data=None, params=None, **_):
        calls.append({"method": method, "path": path, "json": json_data})
        return {"key": "sk-test", "token": "tok"}

    monkeypatch.setattr(litellm_client, "_request", fake)


@pytest.mark.asyncio
async def test_create_key_sends_object_permission(monkeypatch):
    calls: list[dict] = []
    await _capture_request(monkeypatch, calls)
    await litellm_client.create_key(
        key_alias="k1",
        object_permission={"mcp_servers": ["docs_mcp_server", "supply_cloud"]},
    )
    body = calls[0]["json"]
    assert body["object_permission"] == {
        "mcp_servers": ["docs_mcp_server", "supply_cloud"]
    }
    assert "allowed_mcp_servers" not in body


@pytest.mark.asyncio
async def test_create_key_without_permission_omits_field(monkeypatch):
    calls: list[dict] = []
    await _capture_request(monkeypatch, calls)
    await litellm_client.create_key(key_alias="k2")
    assert "object_permission" not in calls[0]["json"]


@pytest.mark.asyncio
async def test_update_key_object_permission_none_means_untouched(monkeypatch):
    calls: list[dict] = []
    await _capture_request(monkeypatch, calls)
    await litellm_client.update_key(key_id="tok", models=["m"])
    assert "object_permission" not in calls[0]["json"]

    await litellm_client.update_key(key_id="tok", object_permission={"mcp_servers": []})
    assert calls[1]["json"]["object_permission"] == {"mcp_servers": []}


@pytest.mark.asyncio
async def test_create_mcp_server_allow_all_keys_follows_flag(monkeypatch):
    calls: list[dict] = []
    await _capture_request(monkeypatch, calls)
    await litellm_client.create_mcp_server(server_name="s1", url="http://x/mcp")
    assert calls[0]["json"]["allow_all_keys"] is False

    await litellm_client.create_mcp_server(
        server_name="s2", url="http://x/mcp", allow_all_keys=True
    )
    assert calls[1]["json"]["allow_all_keys"] is True


def _server(**kw):
    base = dict(is_public=False, sync_to_litellm=True, public_reason=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_public_flag_requires_reason():
    with pytest.raises(ValidationError):
        mcp_service._validate_public_flag(_server(is_public=True))


def test_public_flag_rejects_catalog_only():
    with pytest.raises(ValidationError):
        mcp_service._validate_public_flag(
            _server(is_public=True, public_reason="理由", sync_to_litellm=False)
        )


def test_public_flag_accepts_reasoned_gateway_server():
    mcp_service._validate_public_flag(
        _server(is_public=True, public_reason="只读文档检索")
    )
    mcp_service._validate_public_flag(_server(is_public=False))


@pytest.mark.asyncio
async def test_push_server_config_passes_is_public(monkeypatch):
    calls: list[dict] = []

    async def fake_update(**kw):
        calls.append(kw)

    async def fake_create(**kw):
        calls.append(kw)

    monkeypatch.setattr(litellm_client, "update_mcp_server", fake_update)
    monkeypatch.setattr(litellm_client, "create_mcp_server", fake_create)

    def snapshot():
        return SimpleNamespace(
            url="http://x/mcp",
            transport="streamableHttp",
            auth_type="none",
            credentials=None,
            instructions="",
            mcp_info={},
            extra_headers=None,
        )

    common = dict(
        server_id="sid",
        server_name="s1",
        description="",
        tools=[],
        external_cost_per_call=0,
    )
    await mcp_service._push_server_config_to_litellm(
        SimpleNamespace(**common, litellm_synced=False, is_public=False), snapshot()
    )
    await mcp_service._push_server_config_to_litellm(
        SimpleNamespace(**common, litellm_synced=True, is_public=True), snapshot()
    )
    assert calls[0]["allow_all_keys"] is False
    assert calls[1]["allow_all_keys"] is True


@pytest.mark.asyncio
async def test_build_object_permission_unions_public_and_skips_catalog(monkeypatch):
    servers = {
        1: SimpleNamespace(server_name="docs_mcp_server", sync_to_litellm=True),
        2: SimpleNamespace(server_name="supply_cloud", sync_to_litellm=True),
        4: SimpleNamespace(server_name="dingtalk-oa", sync_to_litellm=False),
    }

    async def fake_find_server_by_id(session, sid):
        return servers.get(sid)

    async def fake_public_names(session):
        return ["docs_mcp_server"]

    monkeypatch.setattr(
        ai_key_service.mcp_repo, "find_server_by_id", fake_find_server_by_id
    )
    monkeypatch.setattr(
        ai_key_service.mcp_repo, "find_public_server_names", fake_public_names
    )

    result = await ai_key_service.build_object_permission(None, [2, 4])
    assert result == {"mcp_servers": ["supply_cloud", "docs_mcp_server"]}


@pytest.mark.asyncio
async def test_build_object_permission_empty_grant_still_sees_public(monkeypatch):
    async def fake_public_names(session):
        return ["docs_mcp_server"]

    monkeypatch.setattr(
        ai_key_service.mcp_repo, "find_public_server_names", fake_public_names
    )
    result = await ai_key_service.build_object_permission(None, [])
    assert result == {"mcp_servers": ["docs_mcp_server"]}


class _FakeSession:
    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, _obj):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("published,expect_broadcast", [(True, True), (False, False)])
async def test_create_server_broadcasts_when_published(
    monkeypatch, published, expect_broadcast
):
    seen: list[object] = []

    async def fake_find_by_url(session, url, transport):
        return None

    async def fake_find_by_name(session, server_name):
        return None

    async def fake_create_server(session, server):
        return server

    async def fake_resolve_publish(session, value):
        return value, False

    async def fake_sync_server(server):
        pass

    async def fake_visibility(session, server):
        seen.append(server)

    async def fake_refresh_tools(session, server_id):
        return []

    async def fake_version_create(session, version):
        return version

    monkeypatch.setattr(
        mcp_service.mcp_repo, "find_server_by_url_and_transport", fake_find_by_url
    )
    monkeypatch.setattr(mcp_service.mcp_repo, "find_server_by_name", fake_find_by_name)
    monkeypatch.setattr(mcp_service.mcp_repo, "create_server", fake_create_server)
    from services import publish_review_service as _prs

    monkeypatch.setattr(_prs, "resolve_publish", fake_resolve_publish)
    monkeypatch.setattr(mcp_service, "_sync_server_to_litellm", fake_sync_server)
    monkeypatch.setattr(mcp_service, "_sync_mcp_visibility", fake_visibility)
    monkeypatch.setattr(mcp_service, "refresh_tools", fake_refresh_tools)
    monkeypatch.setattr(mcp_service.mcp_version_repo, "create", fake_version_create)
    from core import url_safety as _us

    monkeypatch.setattr(_us, "validate_url", lambda url, **kw: None)

    await mcp_service.create_server(
        _FakeSession(),
        name="探针",
        server_name="probe_server",
        url="http://127.0.0.1:1/mcp",
        is_published=published,
    )
    assert bool(seen) is expect_broadcast


# ─── 回填脚本的纯函数 ────────────────────────────────────────────────────────


def test_backfill_names_of_skips_catalog_only():
    from scripts import backfill_key_mcp_permissions as bf

    servers = {
        1: SimpleNamespace(server_name="docs_mcp_server", sync_to_litellm=True),
        4: SimpleNamespace(server_name="dingtalk-oa", sync_to_litellm=False),
    }
    assert bf._names_of([1, 4, 999], servers) == ["docs_mcp_server"]


def test_backfill_current_permission_reads_nested_info():
    from scripts import backfill_key_mcp_permissions as bf

    info = {"key": "x", "info": {"object_permission": {"mcp_servers": ["a", "b"]}}}
    assert bf._current_permission(info) == ["a", "b"]
    assert bf._current_permission({}) is None
    assert bf._current_permission(None) is None
