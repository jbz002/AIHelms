"""贡献者已发布资源编辑锁 + MCP 编辑白名单校验。

修复 code review 发现的两点：
- PUT 已发布资源 → 409（与 delete 一致；防 owner 绕审核改线上元数据/接入地址）
- MCP UpdateMcpRequest 剥 url/transport（接入地址变更强制走 version，防直改主表 url
  即时同步 LiteLLM、绕过版本审核）
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from api.v1 import contributor_agents as ca
from api.v1.contributor_agents import CreateAgentRequest, UpdateAgentRequest
from api.v1.contributor_mcps import UpdateMcpRequest
from core.database import get_worker_session_factory
from models.db import Agent, PublishReview, User
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


async def _create_agent(owner_id: int) -> dict:
    req = CreateAgentRequest(name=f"pl{uuid.uuid4().hex[:10]}", platform="web")
    session = _session()
    try:
        data = await ca.create_my_agent(
            req, session=session, current_user=_user(owner_id)
        )
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
async def test_update_published_agent_blocked():
    """已发布智能体对 contributor 不可编辑（409），与 delete 行为一致。"""
    owner, _ = await _two_user_ids()
    created = await _create_agent(owner)
    agent_id = int(created["id"])
    try:
        async with _session() as s:
            await ca.agent_service.set_published(s, agent_id, True)
            await s.commit()

        session = _session()
        req = UpdateAgentRequest(name="should-not-apply")
        with pytest.raises(HTTPException) as exc:
            await ca.update_my_agent(
                agent_id, req, session=session, current_user=_user(owner)
            )
        await session.close()
        assert exc.value.status_code == 409

        # 元数据未被改写
        async with _session() as s:
            agent = await ca.agent_repo.find_by_id(s, agent_id)
            assert agent.name == created["name"]
    finally:
        await _cleanup([agent_id])


def test_mcp_update_whitelist_excludes_url_and_transport():
    """MCP 编辑白名单不含 url/transport —— 接入地址变更必须走 version 端点。"""
    fields = set(UpdateMcpRequest.model_fields.keys())
    assert "url" not in fields
    assert "transport" not in fields
    # 关键元数据仍可编辑
    assert "name" in fields
    assert "description" in fields
