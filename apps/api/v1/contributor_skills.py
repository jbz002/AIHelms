"""贡献者 Skill router — 普通用户在 web 端贡献自己的 Skill 草稿。

与 admin 的 skills.py 正交：
- 守卫统一 require_permission("skill:contribute")（admin 由 is_admin 放行，无需此码）。
- 所有权强制：每个端点经 _require_owned 比对 Skill.created_by == 当前用户，404 非 403。
- 草稿语义：create 硬编码 is_published=False / requires_approval=True，防绕审核直接发布。
- 激活版本、安全审查、审核通过/驳回仍归 admin（skill:update / ai_policies:scan / publish_review:approve）。
"""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import Skill
from repositories import skill_repo
from services import publish_review_service, skill_service
from services.skill_serializers import _serialize

router = APIRouter(prefix="/contributor/skills", tags=["贡献者 Skill"])


async def _require_owned(session: AsyncSession, skill_id: int, uid: int) -> Skill:
    """加载 skill 并校验归属当前用户；不存在或不归属均返回 404（防存在性泄漏）。"""
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill or skill.created_by != uid:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return skill


@router.get("", summary="我的 Skill 列表")
async def list_my_skills(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:contribute")),
):
    uid = current_user["id"]
    skills = await skill_repo.find_all_by_creator(session, uid, page, page_size)
    total = await skill_repo.count_by_creator(session, uid)
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "items": [_serialize(s) for s in skills],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.get("/{skill_id}", summary="我的 Skill 详情")
async def get_my_skill(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:contribute")),
):
    skill = await _require_owned(session, skill_id, current_user["id"])
    return {"code": 200, "message": "ok", "data": _serialize(skill)}


@router.post("", summary="创建我的 Skill 草稿")
async def create_my_skill(
    name: str = Form(...),
    icon: str = Form("📦"),
    icon_url: str | None = Form(None, max_length=500),
    description: str = Form(""),
    category: str = Form("general"),
    version: str = Form("1.0.0"),
    tags: str = Form("[]"),
    author: str = Form(""),
    agent_install_prompt: str = Form(""),
    usage_instructions: str = Form(""),
    visibility_type: str = Form("all"),
    source_url: str = Form(""),
    zip_file: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:contribute")),
):
    try:
        tags_list = json.loads(tags) if tags else []
    except json.JSONDecodeError:
        tags_list = []
    zip_content = None
    zip_filename = ""
    if zip_file is not None and zip_file.filename:
        zip_content = await zip_file.read()
        zip_filename = zip_file.filename
    try:
        data = await skill_service.create_skill(
            session,
            name=name,
            icon=icon,
            icon_url=icon_url,
            description=description,
            category=category,
            version=version,
            tags=tags_list,
            author=author,
            agent_install_prompt=agent_install_prompt,
            usage_instructions=usage_instructions,
            is_published=False,
            requires_approval=True,
            visibility_type=visibility_type,
            zip_content=zip_content,
            zip_filename=zip_filename,
            source_url=source_url or None,
            created_by=current_user["id"],
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "Skill 草稿创建成功", "data": data}


@router.put("/{skill_id}", summary="更新我的 Skill 草稿")
async def update_my_skill(
    skill_id: int,
    name: str | None = Form(None),
    icon: str | None = Form(None),
    icon_url: str | None = Form(None, max_length=500),
    description: str | None = Form(None),
    category: str | None = Form(None),
    version: str | None = Form(None),
    tags: str | None = Form(None),
    author: str | None = Form(None),
    agent_install_prompt: str | None = Form(None),
    usage_instructions: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:contribute")),
):
    skill = await _require_owned(session, skill_id, current_user["id"])
    if skill.is_published:
        raise HTTPException(
            status_code=409,
            detail="已发布的 Skill 不可编辑，如需修改请新建版本或联系管理员",
        )
    kwargs: dict = {}
    if name is not None:
        kwargs["name"] = name
    if icon is not None:
        kwargs["icon"] = icon
    if icon_url is not None:
        kwargs["icon_url"] = icon_url
    if description is not None:
        kwargs["description"] = description
    if category is not None:
        kwargs["category"] = category
    if version is not None:
        kwargs["version"] = version
    if tags is not None:
        try:
            kwargs["tags"] = json.loads(tags)
        except json.JSONDecodeError:
            kwargs["tags"] = []
    if author is not None:
        kwargs["author"] = author
    if agent_install_prompt is not None:
        kwargs["agent_install_prompt"] = agent_install_prompt
    if usage_instructions is not None:
        kwargs["usage_instructions"] = usage_instructions
    try:
        data = await skill_service.update_skill(
            session,
            skill_id,
            actor_id=current_user["id"],
            zip_content=None,
            zip_filename=None,
            **kwargs,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "Skill 更新成功", "data": data}


@router.post("/{skill_id}/versions", summary="创建我的 Skill 新版本")
async def create_my_skill_version(
    skill_id: int,
    version: str = Form(...),
    version_label: str = Form(""),
    change_log: str = Form(""),
    zip_file: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:contribute")),
):
    await _require_owned(session, skill_id, current_user["id"])
    zip_content = None
    zip_filename = ""
    if zip_file is not None and zip_file.filename:
        zip_content = await zip_file.read()
        zip_filename = zip_file.filename
    try:
        data = await skill_service.create_version(
            session,
            skill_id,
            version=version,
            version_label=version_label,
            change_log=change_log,
            zip_content=zip_content,
            zip_filename=zip_filename,
            created_by=current_user["id"],
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "Skill 版本创建成功", "data": data}


@router.delete("/{skill_id}", summary="删除我的 Skill 草稿")
async def delete_my_skill(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:contribute")),
):
    skill = await _require_owned(session, skill_id, current_user["id"])
    if skill.is_published:
        raise HTTPException(
            status_code=409, detail="已发布的 Skill 不可删除，请联系管理员"
        )
    try:
        await skill_service.delete_skill(session, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "Skill 删除成功", "data": None}


@router.post("/{skill_id}/submit-review", summary="提交我的 Skill 发布审核")
async def submit_my_skill_review(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:contribute")),
):
    skill = await _require_owned(session, skill_id, current_user["id"])
    if skill.is_published:
        raise HTTPException(status_code=409, detail="Skill 已发布，无需重复提交审核")
    try:
        review = await publish_review_service.submit_review(
            session,
            publish_review_service.ENTITY_SKILL,
            skill_id,
            current_user["id"],
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "code": 200,
        "message": "发布审核已提交",
        "data": publish_review_service._serialize(review),
    }
