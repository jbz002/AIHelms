"""S4 · Skill 治理端点：版本别名 Tag + 治理 Label。

与 skills.py 同 prefix="/skills"，独立成文件避免 skills.py 继续膨胀。
- Tag（版本别名 beta/stable）：skill:update（版本作者动作）。
- Label / label_definitions（治理标签）：skill:label:manage（admin-only by is_admin bypass）。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from exceptions import ConflictError, NotFoundError, ValidationError
from repositories import skill_label_repo, skill_repo
from services import builtin_skills_service, skill_label_service, skill_tag_service
from services.skill_serializers import _latest_audit_map, _serialize

router = APIRouter(prefix="/skills", tags=["skills"])


class CreateLabelDefinitionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    display_name_key: str = Field(..., min_length=1, max_length=64)
    color: str = Field("", max_length=16, pattern=r"^[a-z0-9]*$")
    sort_order: int = 0
    is_active: bool = True


class UpdateLabelDefinitionRequest(BaseModel):
    display_name_key: str | None = Field(None, max_length=64)
    color: str | None = Field(None, max_length=16, pattern=r"^[a-z0-9]*$")
    sort_order: int | None = None
    is_active: bool | None = None


class CreateTagRequest(BaseModel):
    tag_name: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-z0-9_.-]+$")
    version_id: int


class GrantLabelRequest(BaseModel):
    label_name: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    note: str = Field("", max_length=500)


# ─── label-definitions（字面路径优先声明，避免与 {skill_id} 冲突）──────────


@router.get("/label-definitions")
async def list_label_definitions(
    active_only: bool = True,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    data = await skill_label_service.list_definitions(session, active_only=active_only)
    return {"code": 200, "message": "ok", "data": data}


@router.post("/label-definitions", summary="创建治理标签定义")
async def create_label_definition(
    req: CreateLabelDefinitionRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:label:manage")),
):
    try:
        data = await skill_label_service.create_definition(
            session,
            name=req.name,
            display_name_key=req.display_name_key,
            color=req.color,
            sort_order=req.sort_order,
            is_active=req.is_active,
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "标签定义创建成功", "data": data}


@router.put("/label-definitions/{definition_id}", summary="更新治理标签定义")
async def update_label_definition(
    definition_id: int,
    req: UpdateLabelDefinitionRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:label:manage")),
):
    try:
        data = await skill_label_service.update_definition(
            session,
            definition_id,
            display_name_key=req.display_name_key,
            color=req.color,
            sort_order=req.sort_order,
            is_active=req.is_active,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="标签定义不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "标签定义更新成功", "data": data}


@router.delete("/label-definitions/{definition_id}", summary="停用治理标签定义")
async def delete_label_definition(
    definition_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:label:manage")),
):
    try:
        await skill_label_service.deactivate_definition(session, definition_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="标签定义不存在")
    return {"code": 200, "message": "标签定义已停用", "data": None}


# ─── 内置 Skills（S8）────────────────────────────────────────────────


@router.get("/builtin", summary="查询内置Skills")
async def list_builtin_skills(
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    skills = await skill_repo.list_builtin(session)
    label_map = await skill_label_repo.map_by_skills(session, [s.id for s in skills])
    latest_audit_map = await _latest_audit_map(session, skills)
    items = [
        _serialize(s, latest_audit_map, labels=label_map.get(s.id)) for s in skills
    ]
    return {"code": 200, "message": "ok", "data": {"items": items, "total": len(items)}}


@router.get("/builtin/status", summary="查询内置Skills同步状态")
async def get_builtin_skills_status(
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    rows = await builtin_skills_service.build_status(session)
    return {"code": 200, "message": "ok", "data": rows}


@router.post("/builtin/sync", status_code=202, summary="重新同步内置Skills")
async def sync_builtin_skills(
    _: dict = Depends(require_permission("skill:label:manage")),
):
    from tasks.builtin_skills_tasks import sync_builtin_skills as _task

    _task.delay()
    return {
        "code": 202,
        "message": "内置 Skills 同步任务已派发",
        "data": {"task": "queued"},
    }


# ─── 版本别名 Tag ───────────────────────────────────────────────────


@router.get("/{skill_id}/tags")
async def list_skill_tags(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    try:
        data = await skill_tag_service.list_tags(session, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.post("/{skill_id}/tags", summary="创建或移动Skill版本标签")
async def create_or_move_skill_tag(
    skill_id: int,
    req: CreateTagRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:update")),
):
    try:
        data = await skill_tag_service.create_or_move_tag(
            session, skill_id, req.tag_name, req.version_id
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="版本不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "版本标签已设置", "data": data}


@router.delete("/{skill_id}/tags/{tag_name}", summary="删除Skill版本标签")
async def delete_skill_tag(
    skill_id: int,
    tag_name: str,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:update")),
):
    try:
        await skill_tag_service.delete_tag(session, skill_id, tag_name)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="标签不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "版本标签已删除", "data": None}


# ─── 治理 Label 授予/撤销 ───────────────────────────────────────────


@router.get("/{skill_id}/labels")
async def list_skill_labels(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    try:
        data = await skill_label_service.list_labels(session, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.post("/{skill_id}/labels", summary="授予Skill治理标签")
async def grant_skill_label(
    skill_id: int,
    req: GrantLabelRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:label:manage")),
):
    try:
        data = await skill_label_service.grant_label(
            session, skill_id, req.label_name, current_user["id"], req.note
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或标签定义不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"code": 200, "message": "治理标签已授予", "data": data}


@router.delete("/{skill_id}/labels/{label_name}", summary="撤销Skill治理标签")
async def revoke_skill_label(
    skill_id: int,
    label_name: str,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:label:manage")),
):
    try:
        await skill_label_service.revoke_label(session, skill_id, label_name)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或未持有该标签")
    return {"code": 200, "message": "治理标签已撤销", "data": None}
