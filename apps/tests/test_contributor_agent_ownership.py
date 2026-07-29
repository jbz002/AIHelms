"""贡献者智能体 router 所有权与草稿语义测试（走真实 DB，无 LiteLLM 依赖）。

覆盖：
- repo find_all_by_creator / count_by_creator 仅返回创建者自己的智能体
- _require_owned：owner 通过，非 owner / 不存在 → 404
- create 强制 is_published=False / requires_approval=True，并写 created_by
- delete 拒绝已发布智能体（409）
- submit-review：owner 可提、非 owner 404、重复 409
- ENTITY_AGENT 审核通过路径：approve → agent_service.set_published → is_published=True
- 路由契约：(method, path) 集合锁定（无 version 端点）
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from api.v1 import contributor_agents as ca
from api.v1.contributor_agents import CreateAgentRequest
from core.database import get_worker_session_factory
from models.db import Agent, PublishReview, User
from repositories import agent_repo
from services import publish_review_service


def _session():
    return get_worker_session_factory()()


async def _two_user_ids() -> tuple[int, int]:
    async with _session() as s:
        result = await s.execute(select(User.id).limit(2))
        ids = [int(r) for r in result.scalars().all()]
        assert len(ids) >= 2, "测试需至少两个真实用户"
        return ids[0], ids[1]


def _user(uid: int) -> dict:
    return {"id": uid, "is_admin": False, "permissions": ["agent:contribute"]}


async def _create_via_router(owner_id: int, name: str | None = None) -> dict:
    name = name or f"ca{uuid.uuid4().hex[:10]}"
    req = CreateAgentRequest(name=name, platform="web")
    session = _session()
    try:
        data = await ca.create_my_agent(req, session=session, current_user=_user(owner_id))
    finally:
        await session.close()
    return data["data"]


async def _cleanup(agent_ids: list[int]) -> None:
    async with _session() as s:
        await s.execute(
            delete(PublishReview).where(
                PublishReview.entity_type == publish_review_service.ENTITY_AGENT,
                PublishReview.entity_id.in_(agent_ids),
            )
        )
        await s.execute(delete(Agent).where(Agent.id.in_(agent_ids)))
        await s.commit()


@pytest.mark.asyncio
async def test_repo_creator_filter_returns_only_own_agents():
    owner, other = await _two_user_ids()
    created = await _create_via_router(owner)
    agent_id = int(created["id"])
    try:
        async with _session() as s:
            own = await agent_repo.find_all_by_creator(s, owner, 1, 50)
            other_list = await agent_repo.find_all_by_creator(s, other, 1, 50)
            assert agent_id in {a.id for a in own}
            assert agent_id not in {a.id for a in other_list}
            assert await agent_repo.count_by_creator(s, owner) >= 1
    finally:
        await _cleanup([agent_id])


@pytest.mark.asyncio
async def test_require_owned_owner_passes_non_owner_404():
    owner, other = await _two_user_ids()
    created = await _create_via_router(owner)
    agent_id = int(created["id"])
    try:
        async with _session() as s:
            agent = await ca._require_owned(s, agent_id, owner)
            assert agent.id == agent_id
            with pytest.raises(HTTPException) as exc:
                await ca._require_owned(s, agent_id, other)
            assert exc.value.status_code == 404
            with pytest.raises(HTTPException) as exc2:
                await ca._require_owned(s, agent_id + 999999, owner)
            assert exc2.value.status_code == 404
    finally:
        await _cleanup([agent_id])


@pytest.mark.asyncio
async def test_create_forces_draft_and_sets_created_by():
    owner, _ = await _two_user_ids()
    created = await _create_via_router(owner)
    agent_id = int(created["id"])
    try:
        assert created["is_published"] is False
        assert created["requires_approval"] is True
        assert created["created_by"] == owner
    finally:
        await _cleanup([agent_id])


@pytest.mark.asyncio
async def test_delete_blocks_published_agent():
    owner, _ = await _two_user_ids()
    created = await _create_via_router(owner)
    agent_id = int(created["id"])
    try:
        async with _session() as s:
            await ca.agent_service.set_published(s, agent_id, True)
            await s.commit()

        session = _session()
        with pytest.raises(HTTPException) as exc:
            await ca.delete_my_agent(agent_id, session=session, current_user=_user(owner))
        await session.close()
        assert exc.value.status_code == 409
    finally:
        await _cleanup([agent_id])


@pytest.mark.asyncio
async def test_submit_review_owner_non_owner_duplicate():
    owner, other = await _two_user_ids()
    created = await _create_via_router(owner)
    agent_id = int(created["id"])
    try:
        session = _session()
        review = await ca.submit_my_agent_review(
            agent_id, session=session, current_user=_user(owner)
        )
        await session.close()
        assert review["data"]["status"] == "pending"
        assert review["data"]["entity_type"] == publish_review_service.ENTITY_AGENT

        session = _session()
        with pytest.raises(HTTPException) as exc:
            await ca.submit_my_agent_review(
                agent_id, session=session, current_user=_user(other)
            )
        await session.close()
        assert exc.value.status_code == 404

        session = _session()
        with pytest.raises(HTTPException) as exc2:
            await ca.submit_my_agent_review(
                agent_id, session=session, current_user=_user(owner)
            )
        await session.close()
        assert exc2.value.status_code == 409
    finally:
        await _cleanup([agent_id])


@pytest.mark.asyncio
async def test_approve_sets_agent_published_via_entity_agent():
    """submit-review(ENTITY_AGENT) → approve → agent_service.set_published → is_published=True。"""
    owner, reviewer = await _two_user_ids()
    created = await _create_via_router(owner)
    agent_id = int(created["id"])
    try:
        session = _session()
        review = await ca.submit_my_agent_review(
            agent_id, session=session, current_user=_user(owner)
        )
        await session.close()
        review_id = int(review["data"]["id"])

        async with _session() as s:
            await publish_review_service.approve(s, review_id, reviewer_id=reviewer)
            agent = await agent_repo.find_by_id(s, agent_id)
            assert agent is not None
            assert agent.is_published is True
    finally:
        await _cleanup([agent_id])


def test_contributor_agent_routes_contract():
    routes = {(sorted(r.methods)[0], r.path) for r in ca.router.routes}
    assert routes == {
        ("GET", "/contributor/agents"),
        ("GET", "/contributor/agents/{agent_id}"),
        ("POST", "/contributor/agents"),
        ("PUT", "/contributor/agents/{agent_id}"),
        ("DELETE", "/contributor/agents/{agent_id}"),
        ("POST", "/contributor/agents/{agent_id}/submit-review"),
    }
