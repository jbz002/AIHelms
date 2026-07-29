"""贡献者智能体 router — 普通用户在 web 端贡献自己的智能体草稿。

与 admin 的 agents.py 正交：
- 守卫统一 require_permission("agent:contribute")（admin 由 is_admin 放行，无需此码）。
- 所有权强制：每个端点经 _require_owned 比对 Agent.created_by == 当前用户，404 非 403。
- 草稿语义：create 硬编码 is_published=False / requires_approval=True，防绕审核直接发布。
- 智能体无版本概念，故无 version 端点。审核通过/驳回仍归 admin（publish_review:approve）。
- agent 实体经 publish_review_service.ENTITY_AGENT 走发布审核（approve 调 agent_service.set_published）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from exceptions import ConflictError, NotFoundError
from models.db import Agent
from repositories import agent_repo
from services import agent_service, publish_review_service

router = APIRouter(prefix="/contributor/agents", tags=["贡献者智能体"])


class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    icon: str = ""
    icon_url: str | None = Field(None, max_length=500)
    description: str = Field("", max_length=2000)
    platform: str = Field(..., min_length=1, max_length=64)
    category: str = Field("general", max_length=50)
    chat_url: str = Field("", max_length=500)
    tags: list[str] = Field(default_factory=list)


class UpdateAgentRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    icon: str | None = None
    icon_url: str | None = Field(None, max_length=500)
    description: str | None = None
    platform: str | None = Field(None, min_length=1, max_length=64)
    category: str | None = None
    chat_url: str | None = None
    tags: list[str] | None = None


async def _require_owned(session: AsyncSession, agent_id: int, uid: int) -> Agent:
    """加载智能体并校验归属当前用户；不存在或不归属均返回 404。"""
    agent = await agent_repo.find_by_id(session, agent_id)
    if not agent or agent.created_by != uid:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return agent


@router.get("", summary="我的智能体列表")
async def list_my_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("agent:contribute")),
):
    uid = current_user["id"]
    items = await agent_repo.find_all_by_creator(session, uid, page, page_size)
    total = await agent_repo.count_by_creator(session, uid)
    serialized = [agent_service._serialize(a) for a in items]
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "items": serialized,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.get("/{agent_id}", summary="我的智能体详情")
async def get_my_agent(
    agent_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("agent:contribute")),
):
    await _require_owned(session, agent_id, current_user["id"])
    try:
        data = await agent_service.get_agent(session, agent_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.post("", summary="创建我的智能体草稿")
async def create_my_agent(
    req: CreateAgentRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("agent:contribute")),
):
    data = await agent_service.create_agent(
        session,
        name=req.name,
        icon=req.icon,
        icon_url=req.icon_url,
        description=req.description,
        platform=req.platform,
        category=req.category,
        chat_url=req.chat_url,
        tags=req.tags,
        is_published=False,
        requires_approval=True,
        created_by=current_user["id"],
    )
    return {"code": 200, "message": "智能体草稿创建成功", "data": data}


@router.put("/{agent_id}", summary="更新我的智能体草稿")
async def update_my_agent(
    agent_id: int,
    req: UpdateAgentRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("agent:contribute")),
):
    agent = await _require_owned(session, agent_id, current_user["id"])
    if agent.is_published:
        raise HTTPException(
            status_code=409, detail="已发布的智能体不可编辑，请联系管理员"
        )
    kwargs = req.model_dump(exclude_none=True)
    try:
        data = await agent_service.update_agent(session, agent_id, **kwargs)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return {"code": 200, "message": "智能体更新成功", "data": data}


@router.delete("/{agent_id}", summary="删除我的智能体草稿")
async def delete_my_agent(
    agent_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("agent:contribute")),
):
    agent = await _require_owned(session, agent_id, current_user["id"])
    if agent.is_published:
        raise HTTPException(
            status_code=409, detail="已发布的智能体不可删除，请联系管理员"
        )
    try:
        await agent_service.delete_agent(session, agent_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return {"code": 200, "message": "智能体删除成功", "data": None}


@router.post("/{agent_id}/submit-review", summary="提交我的智能体发布审核")
async def submit_my_agent_review(
    agent_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("agent:contribute")),
):
    agent = await _require_owned(session, agent_id, current_user["id"])
    if agent.is_published:
        raise HTTPException(status_code=409, detail="智能体已发布，无需重复提交审核")
    try:
        review = await publish_review_service.submit_review(
            session,
            publish_review_service.ENTITY_AGENT,
            agent_id,
            current_user["id"],
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "code": 200,
        "message": "发布审核已提交",
        "data": publish_review_service._serialize(review),
    }
