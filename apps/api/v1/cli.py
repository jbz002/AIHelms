"""S7 · CLI 分发通道 REST API。

独立 /api/v1/cli/* 前缀，全部 CLI scoped token 鉴权 + scope 校验。
Skill 坐标用 UUID skill_id 字符串（无 slug/namespace）。
只读 + 下载（阶段一）+ 发布新版本（阶段二）。
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_cli_token_identity, get_db, require_cli_scope
from exceptions import ConflictError, NotFoundError, ValidationError
from repositories import skill_label_repo, skill_repo, skill_version_repo
from services import (
    skill_label_service,
    skill_service,
    skill_tag_service,
    skill_view_service,
)
from services.skill_serializers import _serialize_version

router = APIRouter(prefix="/cli", tags=["cli"])


async def _resolve_skill(session: AsyncSession, identifier: str):
    """按 UUID skill_id 解析已发布、未下架的 Skill，否则 404。"""
    skill = await skill_repo.find_by_skill_id(session, identifier)
    if not skill or not skill.is_published or skill.hidden:
        raise HTTPException(status_code=404, detail="Skill 不存在或未发布")
    return skill


@router.get("/auth/whoami")
async def cli_whoami(identity: dict = Depends(get_cli_token_identity)):
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "owner_id": identity["owner_id"],
            "owner_type": identity["owner_type"],
            "scopes": identity["scopes"],
        },
    }


@router.get("/skills")
async def cli_list_skills(
    q: str | None = Query(None, max_length=128),
    category: str | None = Query(None, max_length=64),
    label: str | None = Query(None, max_length=32),
    sort: str = Query("newest", pattern=r"^(newest|install_count|name)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_cli_scope("skill:search")),
):
    label_skill_ids = None
    if label:
        label_skill_ids = await skill_label_repo.find_skill_ids_by_label_name(
            session, label
        )
    total = await skill_repo.cli_count_skills(
        session,
        q=q,
        category=category,
        label_skill_ids=label_skill_ids,
        sort=sort,
    )
    items = await skill_repo.cli_search_skills(
        session,
        q=q,
        category=category,
        label_skill_ids=label_skill_ids,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    label_map = await skill_label_repo.map_by_skills(session, [s.id for s in items])
    data = {
        "items": [
            {
                "id": s.id,
                "skill_id": s.skill_id,
                "name": s.name,
                "icon": s.icon,
                "description": s.description,
                "version": s.version,
                "category": s.category,
                "author": s.author,
                "install_count": s.install_count,
                "labels": [lb.get("name") for lb in (label_map.get(s.id) or [])],
            }
            for s in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
    return {"code": 200, "message": "ok", "data": data}


@router.get("/skills/{identifier}")
async def cli_get_skill(
    identifier: str,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_cli_scope("skill:read")),
):
    skill = await _resolve_skill(session, identifier)
    try:
        data = await skill_view_service.get_skill_full(session, skill.id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在或未发布")
    data["skill_id"] = skill.skill_id
    data["category"] = skill.category
    data["icon"] = skill.icon
    data["author"] = skill.author
    data["install_count"] = skill.install_count
    return {"code": 200, "message": "ok", "data": data}


@router.get("/skills/{identifier}/download")
async def cli_download_skill(
    identifier: str,
    version: str | None = Query(None, max_length=64),
    session: AsyncSession = Depends(get_db),
    identity: dict = Depends(require_cli_scope("skill:install")),
):
    skill = await _resolve_skill(session, identifier)
    if skill.requires_approval:
        raise HTTPException(
            status_code=403,
            detail="需审批 Skill 暂不支持 CLI 下载，请通过 web 端申请",
        )
    if version:
        ver = await skill_version_repo.find_by_skill_and_version(
            session, skill.id, version
        )
        if not ver or ver.lifecycle_status != "published":
            raise HTTPException(status_code=404, detail="版本不存在或未发布")
        if not ver.zip_path:
            raise HTTPException(status_code=404, detail="版本 zip 不存在")
        await skill_service.record_skill_usage(
            session,
            user_id=identity["owner_id"],
            skill_id=skill.id,
            action="cli_download",
            ai_key_id=identity["ai_key_id"],
        )
        return FileResponse(
            ver.zip_path,
            filename=ver.zip_filename or f"{skill.name}.zip",
            media_type="application/zip",
        )
    try:
        zip_path, download_name, _ = await skill_service.get_skill_zip(
            session, skill.id, require_published=True
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或 zip 文件不存在")
    await skill_service.record_skill_usage(
        session,
        user_id=identity["owner_id"],
        skill_id=skill.id,
        action="cli_download",
        ai_key_id=identity["ai_key_id"],
    )
    return FileResponse(zip_path, filename=download_name, media_type="application/zip")


@router.get("/skills/{identifier}/versions")
async def cli_list_versions(
    identifier: str,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_cli_scope("skill:read")),
):
    skill = await _resolve_skill(session, identifier)
    versions = await skill_version_repo.list_versions(
        session, skill.id, include_deprecated=False
    )
    data = [_serialize_version(v) for v in versions]
    return {"code": 200, "message": "ok", "data": data}


@router.get("/skills/{identifier}/tags")
async def cli_list_tags(
    identifier: str,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_cli_scope("skill:tag:read")),
):
    skill = await _resolve_skill(session, identifier)
    try:
        data = await skill_tag_service.list_tags(session, skill.id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.get("/skills/{identifier}/labels")
async def cli_list_labels(
    identifier: str,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_cli_scope("skill:label:read")),
):
    skill = await _resolve_skill(session, identifier)
    try:
        data = await skill_label_service.list_labels(session, skill.id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.post("/skills/{identifier}/versions", summary="发布 Skill 版本")
async def cli_publish_version(
    identifier: str,
    version: str = Form(...),
    version_label: str = Form(""),
    change_log: str = Form(""),
    zip_file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    identity: dict = Depends(require_cli_scope("skill:publish")),
):
    if identity["owner_type"] != "user":
        raise HTTPException(status_code=403, detail="CLI publish 仅支持 user 类型令牌")
    skill = await _resolve_skill(session, identifier)
    zip_content = await zip_file.read()
    zip_filename = zip_file.filename or ""
    try:
        vdata = await skill_service.create_version(
            session,
            skill.id,
            version=version,
            version_label=version_label,
            change_log=change_log,
            zip_content=zip_content,
            zip_filename=zip_filename,
            created_by=identity["owner_id"],
        )
        result = await skill_service.submit_version_review(
            session, skill.id, int(vdata["id"]), identity["owner_id"]
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await skill_service.record_skill_usage(
        session,
        identity["owner_id"],
        skill.id,
        "cli_publish",
        identity["ai_key_id"],
    )
    return {"code": 200, "message": "版本已提交审核", "data": result}
