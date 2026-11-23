"""MCP 目录登记开关（sync_to_litellm=False）集成测试。

走真实 DB（依赖 dev 中间件运行）+ stub LiteLLM，覆盖：
- create_server(sync_to_litellm=False)：落库、发布，但对 LiteLLM 零调用、零工具拉取
- update_server：字段更新不触发同步
- activate_version：on_sync 走 no-op，active 正常翻转
- health_check_server：显式 ValidationError（目录型无数据面可探测）
- delete_server：不向 LiteLLM 发禁用
- 对照组：sync_to_litellm=True（默认）行为与既有链路一致（create 有调用）
- 切换语义：目录型切回同步型，update 即补同步（update 分支幂等）
"""

import pytest
from sqlalchemy import delete, select

from core.database import get_worker_session_factory
from exceptions import ValidationError
from models.db import McpServer, McpServerVersion
from repositories import mcp_version_repo
from services import litellm_client, mcp_service


def _session():
    return get_worker_session_factory()()


def _stub_litellm(monkeypatch):
    """Stub LiteLLM 调用，记录全部出站调用。"""
    from core import url_safety as _us

    monkeypatch.setattr(_us, "validate_url", lambda url, **kw: None)
    calls = {"create": [], "update": [], "tools": [], "test": [], "delete": []}

    async def fake_create(**kw):
        calls["create"].append(kw)
        return {}

    async def fake_update(**kw):
        calls["update"].append(kw)
        return {}

    async def fake_tools(**kw):
        calls["tools"].append(kw)
        return []

    async def fake_test(**kw):
        calls["test"].append(kw)
        return {}

    monkeypatch.setattr(litellm_client, "create_mcp_server", fake_create)
    monkeypatch.setattr(litellm_client, "update_mcp_server", fake_update)
    monkeypatch.setattr(litellm_client, "list_mcp_tools_from_server", fake_tools)
    monkeypatch.setattr(litellm_client, "test_mcp_connection", fake_test)
    return calls


async def _cleanup(server_names: list[str]):
    async with _session() as session:
        ids = (
            (
                await session.execute(
                    select(McpServer.id).where(McpServer.server_name.in_(server_names))
                )
            )
            .scalars()
            .all()
        )
        if ids:
            await session.execute(
                delete(McpServerVersion).where(McpServerVersion.server_id.in_(ids))
            )
            await session.execute(delete(McpServer).where(McpServer.id.in_(ids)))
        await session.commit()


@pytest.fixture
async def catalog_server(monkeypatch):
    calls = _stub_litellm(monkeypatch)
    async with _session() as session:
        data = await mcp_service.create_server(
            session,
            name="目录登记测试",
            server_name="catalog_probe_server",
            url="https://mcp-gw.example.com/mcp",
            transport="streamableHttp",
            description="目录登记型探针",
            is_published=True,
            sync_to_litellm=False,
        )
        server_row_id = data["id"]
    yield calls, server_row_id
    await _cleanup(["catalog_probe_server"])


async def test_create_catalog_only_skips_litellm(catalog_server):
    calls, row_id = catalog_server
    assert calls["create"] == []
    assert calls["update"] == []
    assert calls["tools"] == []

    async with _session() as session:
        server = await mcp_service.get_server(session, row_id)
        assert server["server_name"] == "catalog_probe_server"
        assert server["is_published"] is True
        assert server["sync_to_litellm"] is False
        assert server["litellm_synced"] is False


async def test_update_catalog_only_skips_sync(catalog_server):
    calls, row_id = catalog_server
    async with _session() as session:
        await mcp_service.update_server(session, row_id, description="改个描述")
    assert calls["update"] == []

    async with _session() as session:
        server = await mcp_service.get_server(session, row_id)
        assert server["description"] == "改个描述"


async def test_health_check_rejected_for_catalog_only(catalog_server):
    _, row_id = catalog_server
    async with _session() as session:
        with pytest.raises(ValidationError):
            await mcp_service.health_check_server(session, row_id)


async def test_activate_version_noop_sync(catalog_server):
    calls, row_id = catalog_server
    async with _session() as session:
        await mcp_service.create_version(
            session,
            row_id,
            version="1.1.0",
            url="https://mcp-gw.example.com/mcp",
            transport="streamableHttp",
            change_log="目录型版本切换",
        )
        version = await mcp_version_repo.find_by_server_and_version(
            session, row_id, "1.1.0"
        )
        await mcp_service.activate_version(session, row_id, version.id)

        server = await mcp_service.get_server(session, row_id)
        active = server.get("active_version")
        assert active is not None
        assert active["version"] == "1.1.0"
        assert active["lifecycle_status"] == "active"
    assert calls["update"] == []


async def test_delete_catalog_only_skips_litellm_disable(catalog_server):
    calls, row_id = catalog_server
    async with _session() as session:
        await mcp_service.delete_server(session, row_id)
    assert calls["update"] == []


async def test_default_create_still_syncs(monkeypatch):
    calls = _stub_litellm(monkeypatch)
    async with _session() as session:
        await mcp_service.create_server(
            session,
            name="同步型对照",
            server_name="sync_probe_server",
            url="https://sync.example.com/mcp",
            transport="streamableHttp",
        )
    assert len(calls["create"]) == 1
    assert calls["create"][0]["server_name"] == "sync_probe_server"
    await _cleanup(["sync_probe_server"])


async def test_flip_back_to_sync_registers(monkeypatch):
    calls = _stub_litellm(monkeypatch)
    async with _session() as session:
        data = await mcp_service.create_server(
            session,
            name="切回同步型",
            server_name="flip_probe_server",
            url="https://flip.example.com/mcp",
            transport="streamableHttp",
            sync_to_litellm=False,
        )
        row_id = data["id"]
        assert calls["create"] == []
        # 切回同步型：本次 update 即补登记（server.litellm_synced=False → create 分支）
        await mcp_service.update_server(session, row_id, sync_to_litellm=True)
        assert len(calls["create"]) == 1
    await _cleanup(["flip_probe_server"])


async def test_catalog_only_allows_hyphen_name(monkeypatch):
    """目录型不进 LiteLLM，server_name 可用连字符（对齐消费端 LibreChat 命名）。"""
    calls = _stub_litellm(monkeypatch)
    async with _session() as session:
        data = await mcp_service.create_server(
            session,
            name="连字符合法探针",
            server_name="dingtalk-probe",
            url="https://mcp-gw.dingtalk.com/oauth/server/oa",
            transport="streamableHttp",
            sync_to_litellm=False,
        )
        assert data["server_name"] == "dingtalk-probe"
    assert calls["create"] == []
    await _cleanup(["dingtalk-probe"])


async def test_synced_name_hyphen_still_rejected(monkeypatch):
    """同步型连字符禁令不放松（LiteLLM 路由限制）。"""
    _stub_litellm(monkeypatch)
    async with _session() as session:
        with pytest.raises(ValidationError, match="LiteLLM"):
            await mcp_service.create_server(
                session,
                name="同步型连字符",
                server_name="bad-hyphen-server",
                url="https://sync.example.com/mcp",
                transport="streamableHttp",
            )
    await _cleanup(["bad-hyphen-server"])


async def test_refresh_tools_rejected_for_catalog_only(catalog_server):
    """手动同步工具对目录型显式拒绝（按人授权平台无法枚举），不再静默 0。"""
    _, row_id = catalog_server
    async with _session() as session:
        with pytest.raises(ValidationError, match="按人授权"):
            await mcp_service.refresh_tools(session, row_id)
