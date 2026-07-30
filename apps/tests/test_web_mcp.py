"""用户自助 MCP server 端到端烟测 + ak- key 权限隔离验证。

铸一个归属普通用户（非 admin）的平台 API Key，经 httpx ASGITransport + asgi-lifespan
打挂载的 FastAPI app（触发 lifespan 初始化两个 MCP 的 StreamableHTTPSessionManager），验证：
- 无 auth → 401
- 普通用户 key 可用 /web-mcp/mcp（initialize / tools/list 暴露钉的高频 / call_tool）
- 同一把普通用户 key 被 /admin-mcp/mcp 拒（401）—— 证明 UserKeyVerifier 与 AdminKeyVerifier
  隔离，且 validate_api_key 已从 creator 派生 is_admin（不再硬编码 True）
- /api-keys/my 自助 CRUD
- /api/v1/web-mcp 状态接口
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
WEB_PATH = "/web-mcp/mcp"
ADMIN_PATH = "/admin-mcp/mcp"

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


async def _pick_user_id(*, admin: bool) -> int:
    async with async_session() as session:
        if admin:
            stmt = (
                select(User.id)
                .where((User.is_admin.is_(True)) | (User.is_super_admin.is_(True)))
                .limit(1)
            )
        else:
            stmt = (
                select(User.id)
                .where(User.is_admin.is_(False), User.is_super_admin.is_(False))
                .limit(1)
            )
        return (await session.execute(stmt)).scalar_one()


async def _mint_key(user_id: int) -> tuple[str, int]:
    raw, prefix, key_hash = generate_api_key()
    async with async_session() as session:
        ak = ApiKey(
            name="web-mcp-smoke",
            key_prefix=prefix,
            key_hash=key_hash,
            is_active=True,
            created_by=user_id,
        )
        ak = await api_key_repo.create(session, ak)
        await session.commit()
        return raw, ak.id


async def _drop_keys(key_ids: list[int]) -> None:
    async with async_session() as session:
        for kid in key_ids:
            obj = await session.get(ApiKey, kid)
            if obj:
                await session.delete(obj)
        await session.commit()


async def test_web_mcp_no_auth_returns_401(client: httpx.AsyncClient) -> None:
    r = await client.post(WEB_PATH, json=_INIT_BODY)
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


async def test_user_key_isolated_between_web_and_admin_mcp(
    client: httpx.AsyncClient,
) -> None:
    """普通用户 key：web-mcp 收，admin-mcp 拒（验证权限隔离 + is_admin 从 creator 派生）。"""
    user_id = await _pick_user_id(admin=False)
    raw, key_id = await _mint_key(user_id)
    try:
        headers = {
            "Authorization": f"Bearer {raw}",
            "Accept": "application/json, text/event-stream",
        }

        # web-mcp：initialize + tools/list
        r = await client.post(WEB_PATH, headers=headers, json=_INIT_BODY)
        assert r.status_code == 200
        assert _parse_sse(r.text)["result"]["protocolVersion"]

        r = await client.post(
            WEB_PATH,
            headers=headers,
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
        )
        assert r.status_code == 200
        names = {t["name"] for t in _parse_sse(r.text)["result"]["tools"]}
        assert "search_tools" in names
        assert "call_tool" in names
        # ALWAYS_VISIBLE 高频工具常驻
        assert "web_get_my_identity" in names
        assert "web_list_my_applications" in names

        # 直调只读工具 web_list_my_applications（按当前 user 过滤）
        r = await client.post(
            WEB_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 3,
                "params": {
                    "name": "web_list_my_applications",
                    "arguments": {"params": {"page": 1, "page_size": 20}},
                },
            },
        )
        assert r.status_code == 200
        result = _parse_sse(r.text)["result"]
        assert result["isError"] is False
        payload = json.loads(result["content"][0]["text"])
        assert {"items", "total", "page", "page_size"} <= set(payload)

        # admin-mcp：同一把普通用户 key 必须被拒（401）
        r = await client.post(ADMIN_PATH, headers=headers, json=_INIT_BODY)
        assert r.status_code == 401
    finally:
        await _drop_keys([key_id])


async def test_my_api_keys_endpoint(client: httpx.AsyncClient) -> None:
    user_id = await _pick_user_id(admin=False)
    raw, key_id = await _mint_key(user_id)
    created_ids = [key_id]
    try:
        headers = {"Authorization": f"Bearer {raw}"}

        # 列出我的 key
        r = await client.get("/api/v1/api-keys/my", headers=headers)
        assert r.status_code == 200
        items = r.json()["data"]["items"]
        assert any(k["id"] == key_id for k in items)
        # 列表不含明文
        assert all("raw_key" not in k for k in items)

        # 自助创建一个新 key（返回明文，仅本次）
        r = await client.post(
            "/api/v1/api-keys/my",
            headers=headers,
            json={"name": "from-test"},
        )
        assert r.status_code == 200
        new_key = r.json()["data"]
        assert new_key["raw_key"]
        assert new_key["created_by"] == user_id
        created_ids.append(new_key["id"])
    finally:
        await _drop_keys(created_ids)


async def test_web_mcp_status_endpoint(client: httpx.AsyncClient) -> None:
    user_id = await _pick_user_id(admin=False)
    raw, key_id = await _mint_key(user_id)
    try:
        r = await client.get("/api/v1/web-mcp", headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["endpoint_url"].endswith("/web-mcp/mcp")
        assert data["tool_count"] >= 6
        assert "web_get_my_identity" in data["tool_names"]
        assert data["has_active_api_key"] is True
    finally:
        await _drop_keys([key_id])
