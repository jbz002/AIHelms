"""MCP 版本管理集成测试。

走真实 DB（依赖 dev 中间件运行）+ stub LiteLLM，覆盖：
- create_server 自动种 v1 active 版本
- create_version 起步为 inactive（灰度）
- activate_version 同步 LiteLLM 并翻转 active（单 active + 主表快照）
- activate 时 LiteLLM 同步失败 → active 回滚（零不一致窗口，核心不变式）
- 单 active 部分唯一索引
- deprecate 守卫 + 默认列表过滤
"""

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from core.database import get_worker_session_factory
from exceptions import ValidationError
from models.db import McpServer, McpServerVersion
from repositories import mcp_version_repo
from services import litellm_client, mcp_service
from services.litellm_client import LiteLLMError


def _session():
    """测试用 NullPool 的 worker session factory，避免 asyncpg QueuePool 连接绑定到
    创建时的事件循环而在 pytest 新事件循环中复用失败。"""
    return get_worker_session_factory()()


def _stub_litellm(monkeypatch, fail_update=False):
    """Stub LiteLLM 调用；fail_update=True 时 update_mcp_server 抛 LiteLLMError。"""
    calls = {"create": [], "update": [], "tools": []}

    async def fake_create(**kw):
        calls["create"].append(kw)
        return {}

    async def fake_update(**kw):
        calls["update"].append(kw)
        if fail_update:
            raise LiteLLMError("simulated litellm failure")
        return {}

    async def fake_tools(**kw):
        calls["tools"].append(kw)
        return []

    async def fake_test(**kw):
        return {}

    monkeypatch.setattr(litellm_client, "create_mcp_server", fake_create)
    monkeypatch.setattr(litellm_client, "update_mcp_server", fake_update)
    monkeypatch.setattr(litellm_client, "list_mcp_tools_from_server", fake_tools)
    monkeypatch.setattr(litellm_client, "test_mcp_connection", fake_test)
    # mock validate_url 避免 DNS 解析触发 SSRF 拦截
    from core import url_safety as _us

    monkeypatch.setattr(_us, "validate_url", lambda url, profile="default": None)
    return calls


async def _make_server(monkeypatch, suffix=None) -> int:
    _stub_litellm(monkeypatch)
    name = f"test_v_{(suffix or uuid.uuid4().hex)[:8]}"
    data = await mcp_service.create_server(
        _session(),
        name=name,
        server_name=name,
        url=f"https://{name}.example.com/mcp",
        transport="sse",
    )
    return data["id"]


async def _cleanup(server_ids: list[int]) -> None:
    async with _session() as s:
        await s.execute(
            delete(McpServerVersion).where(McpServerVersion.server_id.in_(server_ids))
        )
        await s.execute(delete(McpServer).where(McpServer.id.in_(server_ids)))
        await s.commit()


@pytest.mark.asyncio
async def test_create_server_seeds_v1_active(monkeypatch):
    server_id = await _make_server(monkeypatch)
    try:
        async with _session() as s:
            versions = await mcp_version_repo.list_versions(s, server_id)
            assert len(versions) == 1
            assert versions[0].version == "1.0.0"
            assert versions[0].is_active is True
            assert versions[0].lifecycle_status == "active"
            server = await s.get(McpServer, server_id)
            assert server.current_version_id == versions[0].id
    finally:
        await _cleanup([server_id])


@pytest.mark.asyncio
async def test_create_version_starts_inactive_and_no_litellm_sync(monkeypatch):
    server_id = await _make_server(monkeypatch)
    try:
        calls = _stub_litellm(monkeypatch)
        session = _session()
        data = await mcp_service.create_version(
            session,
            server_id,
            version="2.0.0",
            url="https://v2.example.com/mcp",
            transport="sse",
            change_log="canary",
        )
        await session.close()
        assert data["is_active"] is False
        assert data["lifecycle_status"] == "inactive"
        # 新版本创建不应触发 LiteLLM 同步（灰度，不影响线上）
        assert calls["update"] == [] and calls["create"] == []
    finally:
        await _cleanup([server_id])


@pytest.mark.asyncio
async def test_activate_version_syncs_litellm_and_flips_active(monkeypatch):
    server_id = await _make_server(monkeypatch)
    try:
        calls = _stub_litellm(monkeypatch)
        session = _session()
        await mcp_service.create_version(
            session,
            server_id,
            version="2.0.0",
            url="https://v2.example.com/mcp",
            transport="sse",
        )
        v2 = await mcp_version_repo.find_by_server_and_version(
            session, server_id, "2.0.0"
        )
        data = await mcp_service.activate_version(session, server_id, v2.id)
        await session.close()

        # LiteLLM 收到 v2 的 url，server_name 跨版本不变
        assert calls["update"], "LiteLLM update_mcp_server 未被调用"
        assert calls["update"][-1]["url"] == "https://v2.example.com/mcp"
        assert calls["update"][-1]["server_name"].startswith("test_v_")
        # 主表快照已切到 v2
        assert data["url"] == "https://v2.example.com/mcp"
        assert data["active_version"]["version"] == "2.0.0"

        async with _session() as s:
            versions = {
                v.version: v for v in await mcp_version_repo.list_versions(s, server_id)
            }
            assert versions["2.0.0"].is_active is True
            assert versions["1.0.0"].is_active is False
    finally:
        await _cleanup([server_id])


@pytest.mark.asyncio
async def test_activate_rolls_back_on_litellm_failure(monkeypatch):
    """核心不变式：LiteLLM 同步失败时 active 不翻转，主表快照不变。"""
    server_id = await _make_server(monkeypatch)
    try:
        # 创建 v2（用成功 stub）
        _stub_litellm(monkeypatch)
        session = _session()
        await mcp_service.create_version(
            session,
            server_id,
            version="2.0.0",
            url="https://v2.example.com/mcp",
            transport="sse",
        )
        v2 = await mcp_version_repo.find_by_server_and_version(
            session, server_id, "2.0.0"
        )
        v2_id = v2.id
        await session.close()

        # 切到失败 stub 后激活
        _stub_litellm(monkeypatch, fail_update=True)
        session = _session()
        with pytest.raises(ValidationError):
            await mcp_service.activate_version(session, server_id, v2_id)
        await session.close()

        # active 仍是 v1，主表 url 仍是 v1
        async with _session() as s:
            versions = {
                v.version: v for v in await mcp_version_repo.list_versions(s, server_id)
            }
            assert versions["1.0.0"].is_active is True
            assert versions["2.0.0"].is_active is False
            assert versions["2.0.0"].lifecycle_status == "inactive"
            server = await s.get(McpServer, server_id)
            assert "v2.example.com" not in (server.url or "")
    finally:
        await _cleanup([server_id])


@pytest.mark.asyncio
async def test_single_active_invariant_enforced_by_index(monkeypatch):
    """部分唯一索引保证每逻辑 Server 至多 1 个 active（DB 层兜底）。"""
    server_id = await _make_server(monkeypatch)
    try:
        async with _session() as s:
            # 直接插入第二条 active 版本，应触发 IntegrityError
            v2 = McpServerVersion(
                server_id=server_id,
                version="2.0.0",
                is_active=True,
                lifecycle_status="active",
                url="https://v2.example.com/mcp",
                transport="sse",
            )
            s.add(v2)
            with pytest.raises(IntegrityError):
                await s.flush()
            await s.rollback()
    finally:
        await _cleanup([server_id])


@pytest.mark.asyncio
async def test_deprecate_guard_and_list_filter(monkeypatch):
    server_id = await _make_server(monkeypatch)
    try:
        _stub_litellm(monkeypatch)
        session = _session()
        await mcp_service.create_version(
            session,
            server_id,
            version="2.0.0",
            url="https://v2.example.com/mcp",
            transport="sse",
        )
        v2 = await mcp_version_repo.find_by_server_and_version(
            session, server_id, "2.0.0"
        )
        # 弃用 active 版本应被拒绝
        v1 = await mcp_version_repo.find_active_for_server(session, server_id)
        with pytest.raises(ValidationError):
            await mcp_service.deprecate_version(session, server_id, v1.id)
        # 弃用 inactive 版本成功
        await mcp_service.deprecate_version(session, server_id, v2.id)
        await session.close()

        # admin 版本列表默认展示全部（含弃用，便于管理）；
        # 显式 include_deprecated=False 才过滤
        session2 = _session()
        default_list = await mcp_service.list_versions(session2, server_id)
        filtered = await mcp_service.list_versions(
            session2, server_id, include_deprecated=False
        )
        await session2.close()
        assert len(default_list) == 2
        assert any(v["lifecycle_status"] == "deprecated" for v in default_list)
        assert all(v["lifecycle_status"] != "deprecated" for v in filtered)
        assert len(filtered) == 1
        assert filtered[0]["lifecycle_status"] == "active"
    finally:
        await _cleanup([server_id])
