"""P1 工具审核：刷新工具清单要保留元数据，定义变更回到 pending。

背景：refresh_tools 是「整表重建」，P0 之前只保留计费信息；P1 若不保留
risk_level / review_status / fields_allowlist，每次刷新都会把审核结果清空。
"""

import pytest
from sqlalchemy import delete, select

from core.database import get_worker_session_factory
from models.db import McpServer, McpServerVersion, McpTool
from repositories import mcp_repo
from services import litellm_client, mcp_service

SERVER_NAME = "tool_review_probe"
STATE = {"tools": []}


def _session():
    return get_worker_session_factory()()


def _stub(monkeypatch):
    from core import url_safety as _us

    monkeypatch.setattr(_us, "validate_url", lambda url, **kw: None)

    async def fake_create(**kw):
        return {}

    async def fake_update(**kw):
        return {}

    async def fake_test(**kw):
        return {}

    async def fake_list(**kw):
        return list(STATE["tools"])

    monkeypatch.setattr(litellm_client, "create_mcp_server", fake_create)
    monkeypatch.setattr(litellm_client, "update_mcp_server", fake_update)
    monkeypatch.setattr(litellm_client, "test_mcp_connection", fake_test)
    monkeypatch.setattr(litellm_client, "list_mcp_tools_from_server", fake_list)


async def _cleanup():
    async with _session() as session:
        row = (
            await session.execute(
                select(McpServer).where(McpServer.server_name == SERVER_NAME)
            )
        ).scalar_one_or_none()
        if row:
            await session.execute(delete(McpTool).where(McpTool.server_id == row.id))
            await session.execute(
                delete(McpServerVersion).where(McpServerVersion.server_id == row.id)
            )
            await session.execute(delete(McpServer).where(McpServer.id == row.id))
        await session.commit()


@pytest.fixture
async def server_id(monkeypatch):
    _stub(monkeypatch)
    STATE["tools"] = [
        {
            "name": "query",
            "description": "只读查询",
            "inputSchema": {"type": "object"},
        }
    ]
    await _cleanup()
    async with _session() as session:
        data = await mcp_service.create_server(
            session,
            name="工具审核探针",
            server_name=SERVER_NAME,
            url="https://mcp-review.example.com/mcp",
            transport="streamableHttp",
            is_published=False,
        )
    yield data["id"]
    await _cleanup()


async def test_refresh_preserves_metadata_and_flags_pending_on_change(server_id):
    async with _session() as session:
        tools = await mcp_service.get_tools(session, server_id)
        assert [t["tool_name"] for t in tools] == ["query"]
        assert tools[0]["tool_key"] == f"{SERVER_NAME}.query"
        assert tools[0]["review_status"] == "approved"
        tool = await mcp_repo.find_tool_by_id(session, tools[0]["id"])
        tool.risk_level = "write"
        tool.fields_allowlist = ["id"]
        await session.commit()

    # 同一 schema 再刷新：元数据必须保留
    async with _session() as session:
        await mcp_service.refresh_tools(session, server_id)
    async with _session() as session:
        tools = await mcp_service.get_tools(session, server_id)
        assert tools[0]["risk_level"] == "write"
        assert tools[0]["fields_allowlist"] == ["id"]
        assert tools[0]["review_status"] == "approved"

    # 定义变更后再刷新：回到 pending，风险级保留待审
    STATE["tools"] = [
        {
            "name": "query",
            "description": "只读查询（描述变了）",
            "inputSchema": {"type": "object"},
        }
    ]
    async with _session() as session:
        await mcp_service.refresh_tools(session, server_id)
    async with _session() as session:
        tools = await mcp_service.get_tools(session, server_id)
        assert tools[0]["review_status"] == "pending"
        assert tools[0]["risk_level"] == "write"
