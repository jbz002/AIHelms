"""S4 · Skill 版本别名 Tag 端点。

与 skills.py 同 prefix="/skills"，独立成文件避免 skills.py 继续膨胀。
Tag（版本别名 beta/stable）：skill:update（版本作者动作）。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from exceptions import NotFoundError, ValidationError
from services import skill_tag_service

router = APIRouter(prefix="/skills", tags=["skills"])


class CreateTagRequest(BaseModel):
    tag_name: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-z0-9_.-]+$")
    version_id: int


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
