"""管理员操作 MCP server 端到端烟测。

铸一个平台 API Key，经 httpx ASGITransport + asgi-lifespan 打挂载的 FastAPI app
（单事件循环，触发 lifespan 初始化 MCP StreamableHTTPSessionManager），验证：
- 无 auth → 401
- 合法 Bearer → initialize / tools/list（search transform 后暴露钉的高频 + search_tools/call_tool）/ search 发现非钉工具 / 直调钉的 admin_list_users
"""

import json

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import select

from core.api_key_utils import generate_api_key
from core.database import async_session
from main import app
from models.db import ApiKey, User
from repositories import api_key_repo

PROTO = "2025-06-18"
MCP_PATH = "/admin-mcp/mcp"

_INIT_BODY = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "id": 1,
    "params": {
        "protocolVersion": PROTO,
        "capabilities": {},
        "clientInfo": {"name": "smoke", "version": "1"},
    },
}


def _parse_sse(text: str) -> dict | None:
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
    return None


@pytest.fixture
async def client():
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _mint_key() -> tuple[str, int]:
    raw, prefix, key_hash = generate_api_key()
    async with async_session() as session:
        admin_id = (
            await session.execute(
                select(User.id).where(User.is_admin.is_(True)).limit(1)
            )
        ).scalar_one()
        ak = ApiKey(
            name="mcp-smoke",
            key_prefix=prefix,
            key_hash=key_hash,
            is_active=True,
            created_by=admin_id,
        )
        ak = await api_key_repo.create(session, ak)
        await session.commit()
        return raw, ak.id


async def _drop_key(key_id: int) -> None:
    async with async_session() as session:
        await session.delete(await session.get(ApiKey, key_id))
        await session.commit()


async def test_no_auth_returns_401(client: httpx.AsyncClient) -> None:
    r = await client.post(MCP_PATH, json=_INIT_BODY)
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


async def test_valid_key_lists_tools_and_calls(client: httpx.AsyncClient) -> None:
    raw, key_id = await _mint_key()
    try:
        headers = {
            "Authorization": f"Bearer {raw}",
            "Accept": "application/json, text/event-stream",
        }

        r = await client.post(MCP_PATH, headers=headers, json=_INIT_BODY)
        assert r.status_code == 200
        assert _parse_sse(r.text)["result"]["protocolVersion"]

        r = await client.post(
            MCP_PATH,
            headers=headers,
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
        )
        assert r.status_code == 200
        names = {t["name"] for t in _parse_sse(r.text)["result"]["tools"]}
        # search transform 后 tools/list 只暴露钉的高频 + search_tools + call_tool
        assert "search_tools" in names
        assert "call_tool" in names
        assert "admin_list_users" in names

        # 非钉工具经 search_tools 按需发现
        r = await client.post(
            MCP_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 4,
                "params": {
                    "name": "search_tools",
                    "arguments": {"pattern": "scene_key"},
                },
            },
        )
        assert r.status_code == 200
        searched = _parse_sse(r.text)["result"]
        assert searched["isError"] is False
        assert "admin_create_scene_key" in searched["content"][0]["text"]

        r = await client.post(
            MCP_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 3,
                "params": {"name": "admin_list_users", "arguments": {"params": {}}},
            },
        )
        assert r.status_code == 200
        result = _parse_sse(r.text)["result"]
        assert result["isError"] is False
        payload = json.loads(result["content"][0]["text"])
        assert {"items", "total", "page", "page_size"} <= set(payload)
    finally:
        await _drop_key(key_id)


async def test_status_returns_meta(client: httpx.AsyncClient) -> None:
    raw, key_id = await _mint_key()
    try:
        r = await client.get(
            "/api/v1/admin-mcp",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["tool_count"] >= 64
        assert data["endpoint_url"].endswith("/admin-mcp/mcp")
        assert data["has_active_api_key"] is True
        assert "admin_list_users" in data["tool_names"]
    finally:
        await _drop_key(key_id)
