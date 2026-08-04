"""贡献者 MCP router 所有权与草稿语义测试（走真实 DB + stub LiteLLM）。

覆盖：
- repo find_all_servers_by_creator / count_servers_by_creator 仅返回创建者自己的 MCP
- _require_owned：owner 通过，非 owner / 不存在 → 404
- create 强制 is_published=False / requires_approval=True，并写 created_by
- delete 拒绝已发布 MCP（409）
- version 创建归属校验（owner 可建，非 owner 404）
- submit-review：owner 可提、非 owner 404、重复 409
- 路由契约：(method, path) 集合锁定
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from api.v1 import contributor_mcps as cm
from api.v1.contributor_mcps import (
    CreateMcpRequest,
    CreateMcpVersionRequest,
)
from core import url_safety as _us
from core.database import get_worker_session_factory
from models.db import McpServer, McpServerVersion, PublishReview, User
from services import litellm_client
from services.litellm_client import LiteLLMError


def _session():
    return get_worker_session_factory()()


async def _two_user_ids() -> tuple[int, int]:
    async with _session() as s:
        result = await s.execute(select(User.id).limit(2))
        ids = [int(r) for r in result.scalars().all()]
        assert len(ids) >= 2, "测试需至少两个真实用户"
        return ids[0], ids[1]


def _stub_litellm(monkeypatch) -> None:
    async def fake_create(**kw):
        return {}

    async def fake_update(**kw):
        return {}

    async def fake_tools(**kw):
        return []

    async def fake_test(**kw):
        return {}

    monkeypatch.setattr(litellm_client, "create_mcp_server", fake_create)
    monkeypatch.setattr(litellm_client, "update_mcp_server", fake_update)
    monkeypatch.setattr(litellm_client, "list_mcp_tools_from_server", fake_tools)
    monkeypatch.setattr(litellm_client, "test_mcp_connection", fake_test)
    # mock validate_url 避免 DNS 解析触发 SSRF 拦截
    monkeypatch.setattr(_us, "validate_url", lambda url, profile="default": None)


def _user(uid: int) -> dict:
    return {"id": uid, "is_admin": False, "permissions": ["mcp:contribute"]}


async def _create_via_router(
    monkeypatch, owner_id: int, name: str | None = None
) -> dict:
    _stub_litellm(monkeypatch)
    name = name or f"cm{uuid.uuid4().hex[:10]}"
    req = CreateMcpRequest(
        name=name,
        server_name=name,
        url=f"https://{name}.example.com/mcp",
        transport="sse",
    )
    session = _session()
    try:
        data = await cm.create_my_mcp(
            req, session=session, current_user=_user(owner_id)
        )
    finally:
        await session.close()
    return data["data"]


async def _cleanup(server_ids: list[int]) -> None:
    async with _session() as s:
        await s.execute(
            delete(PublishReview).where(
                PublishReview.entity_type == cm.publish_review_service.ENTITY_MCP,
                PublishReview.entity_id.in_(server_ids),
            )
        )
        await s.execute(
            delete(McpServerVersion).where(McpServerVersion.server_id.in_(server_ids))
        )
        await s.execute(delete(McpServer).where(McpServer.id.in_(server_ids)))
        await s.commit()


@pytest.mark.asyncio
async def test_repo_creator_filter_returns_only_own_mcps(monkeypatch):
    owner, other = await _two_user_ids()
    created = await _create_via_router(monkeypatch, owner)
    server_id = int(created["id"])
    try:
        async with _session() as s:
            own = await cm.mcp_repo.find_all_servers_by_creator(s, owner, 1, 50)
            other_list = await cm.mcp_repo.find_all_servers_by_creator(s, other, 1, 50)
            assert server_id in {srv.id for srv in own}
            assert server_id not in {srv.id for srv in other_list}
            assert await cm.mcp_repo.count_servers_by_creator(s, owner) >= 1
    finally:
        await _cleanup([server_id])


@pytest.mark.asyncio
async def test_require_owned_owner_passes_non_owner_404(monkeypatch):
    owner, other = await _two_user_ids()
    created = await _create_via_router(monkeypatch, owner)
    server_id = int(created["id"])
    try:
        async with _session() as s:
            server = await cm._require_owned(s, server_id, owner)
            assert server.id == server_id
            with pytest.raises(HTTPException) as exc:
                await cm._require_owned(s, server_id, other)
            assert exc.value.status_code == 404
            with pytest.raises(HTTPException) as exc2:
                await cm._require_owned(s, server_id + 999999, owner)
            assert exc2.value.status_code == 404
    finally:
        await _cleanup([server_id])


@pytest.mark.asyncio
async def test_create_forces_draft_and_sets_created_by(monkeypatch):
    owner, _ = await _two_user_ids()
    created = await _create_via_router(monkeypatch, owner)
    server_id = int(created["id"])
    try:
        assert created["is_published"] is False
        assert created["requires_approval"] is True
        assert created["created_by"] == owner
    finally:
        await _cleanup([server_id])


@pytest.mark.asyncio
async def test_delete_blocks_published_mcp(monkeypatch):
    owner, _ = await _two_user_ids()
    created = await _create_via_router(monkeypatch, owner)
    server_id = int(created["id"])
    try:
        async with _session() as s:
            await cm.mcp_service.set_published(s, server_id, True)
            await s.commit()

        session = _session()
        with pytest.raises(HTTPException) as exc:
            await cm.delete_my_mcp(
                server_id, session=session, current_user=_user(owner)
            )
        await session.close()
        assert exc.value.status_code == 409
    finally:
        await _cleanup([server_id])


@pytest.mark.asyncio
async def test_version_create_owner_ok_non_owner_404(monkeypatch):
    owner, other = await _two_user_ids()
    created = await _create_via_router(monkeypatch, owner)
    server_id = int(created["id"])
    try:
        req = CreateMcpVersionRequest(
            version="1.0.1",
            url=f"https://v{server_id}.example.com/mcp",
            transport="sse",
        )
        session = _session()
        data = await cm.create_my_mcp_version(
            server_id, req, session=session, current_user=_user(owner)
        )
        await session.close()
        assert data["data"]["version"] == "1.0.1"

        session = _session()
        with pytest.raises(HTTPException) as exc:
            await cm.create_my_mcp_version(
                server_id,
                CreateMcpVersionRequest(
                    version="1.0.2",
                    url=f"https://v2{server_id}.example.com/mcp",
                    transport="sse",
                ),
                session=session,
                current_user=_user(other),
            )
        await session.close()
        assert exc.value.status_code == 404
    finally:
        await _cleanup([server_id])


@pytest.mark.asyncio
async def test_submit_review_owner_non_owner_duplicate(monkeypatch):
    owner, other = await _two_user_ids()
    created = await _create_via_router(monkeypatch, owner)
    server_id = int(created["id"])
    try:
        session = _session()
        review = await cm.submit_my_mcp_review(
            server_id, session=session, current_user=_user(owner)
        )
        await session.close()
        assert review["data"]["status"] == "pending"

        session = _session()
        with pytest.raises(HTTPException) as exc:
            await cm.submit_my_mcp_review(
                server_id, session=session, current_user=_user(other)
            )
        await session.close()
        assert exc.value.status_code == 404

        session = _session()
        with pytest.raises(HTTPException) as exc2:
            await cm.submit_my_mcp_review(
                server_id, session=session, current_user=_user(owner)
            )
        await session.close()
        assert exc2.value.status_code == 409
    finally:
        await _cleanup([server_id])


def test_contributor_mcp_routes_contract():
    routes = {(sorted(r.methods)[0], r.path) for r in cm.router.routes}
    assert routes == {
        ("GET", "/contributor/mcps"),
        ("GET", "/contributor/mcps/{server_id}"),
        ("POST", "/contributor/mcps"),
        ("PUT", "/contributor/mcps/{server_id}"),
        ("DELETE", "/contributor/mcps/{server_id}"),
        ("POST", "/contributor/mcps/{server_id}/versions"),
        ("POST", "/contributor/mcps/{server_id}/submit-review"),
    }
