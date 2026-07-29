import json
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_ai_key_identity, get_current_user, get_db, require_permission
from core.public_urls import resolve_platform_public_url
from exceptions import ConflictError, NotFoundError, ValidationError
from repositories import skill_repo
from services import (
    ai_policies_service,
    builtin_skills_service,
    skill_drift_service,
    skill_service,
    skill_view_service,
)
from services.skill_serializers import _latest_audit_map, _serialize
from services.visibility_service import can_access

router = APIRouter(prefix="/skills", tags=["skills"])


class CreateCategoryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field("", max_length=200)
    sort_order: int = 0


class DeprecateVersionRequest(BaseModel):
    sunset_date: datetime | None = None


class ResyncVersionRequest(BaseModel):
    new_version: str | None = Field(None, max_length=64)


class SetHiddenRequest(BaseModel):
    hidden: bool


@router.get("/categories")
async def list_categories(
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    data = await skill_service.list_categories(session)
    return {"code": 200, "message": "ok", "data": data}


@router.post("/categories", summary="创建 Skill 分类")
async def create_category(
    req: CreateCategoryRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:create")),
):
    try:
        data = await skill_service.create_category(
            session,
            name=req.name,
            description=req.description,
            sort_order=req.sort_order,
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"code": 200, "message": "分类创建成功", "data": data}


@router.delete("/categories/{category_id}", summary="删除 Skill 分类")
async def delete_category(
    category_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:delete")),
):
    try:
        await skill_service.delete_category(session, category_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="分类不存在")
    return {"code": 200, "message": "分类删除成功", "data": None}


@router.get("/published")
async def list_published_skills(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: str | None = None,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """公开接口：已认证用户可查看已发布的 Skill 列表。"""
    data = await skill_service.list_skills(
        session,
        page,
        page_size,
        category,
        is_published=True,
        viewer_id=current_user["id"],
        is_admin=current_user["is_admin"],
    )
    return {"code": 200, "message": "ok", "data": data}


@router.get("")
async def list_skills(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: str | None = None,
    is_published: bool | None = None,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    data = await skill_service.list_skills(
        session, page, page_size, category, is_published
    )
    return {"code": 200, "message": "ok", "data": data}


# ─── 内置 Skills（S8）────────────────────────────────────────────────


@router.get("/builtin", summary="查询内置Skills")
async def list_builtin_skills(
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    skills = await skill_repo.list_builtin(session)
    latest_audit_map = await _latest_audit_map(session, skills)
    items = [_serialize(s, latest_audit_map) for s in skills]
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
    _: dict = Depends(require_permission("skill:update")),
):
    from tasks.builtin_skills_tasks import sync_builtin_skills as _task

    _task.delay()
    return {
        "code": 202,
        "message": "内置 Skills 同步任务已派发",
        "data": {"task": "queued"},
    }


@router.get("/{skill_id}")
async def get_skill(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    try:
        data = await skill_service.get_skill(session, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.get("/{skill_id}/market-detail")
async def get_skill_market_detail(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """直链详情：all/selected/unlisted 登录可读，private 仅创建者+管理员。"""
    try:
        data = await skill_service.get_skill(session, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    if not can_access(
        current_user["id"],
        current_user["is_admin"],
        data.get("visibility_type", "all"),
        data.get("created_by"),
    ):
        raise HTTPException(status_code=403, detail="无权访问该资源")
    return {"code": 200, "message": "ok", "data": data}


# ─── Progressive Disclosure Views ─────────────────────────────────────────


@router.get("/{skill_id}/card")
async def get_skill_card(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    try:
        data = await skill_view_service.get_skill_card(session, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.get("/{skill_id}/summary")
async def get_skill_summary(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    try:
        data = await skill_view_service.get_skill_summary(session, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.get("/{skill_id}/full")
async def get_skill_full(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    try:
        data = await skill_view_service.get_skill_full(session, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.get("/{skill_id}/integrity", summary="Skill 内容完整性信息")
async def get_skill_integrity(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    try:
        data = await skill_view_service.get_skill_integrity(session, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


# ─── Skill Versions ───────────────────────────────────────────────────────────


@router.get("/{skill_id}/versions")
async def list_skill_versions(
    skill_id: int,
    include_deprecated: bool = Query(True),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:read")),
):
    try:
        data = await skill_service.list_versions(session, skill_id, include_deprecated)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.post("/{skill_id}/versions", summary="创建Skill新版本")
async def create_skill_version(
    skill_id: int,
    version: str = Form(...),
    version_label: str = Form(""),
    change_log: str = Form(""),
    zip_file: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:create")),
):
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
    return {"code": 200, "message": "Skill 版本创建成功", "data": data}


@router.post("/{skill_id}/versions/{version_id}/activate", summary="激活Skill版本")
async def activate_skill_version(
    skill_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:update")),
):
    try:
        data = await skill_service.activate_version(session, skill_id, version_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或版本不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "Skill 版本已激活", "data": data}


@router.post("/{skill_id}/versions/{version_id}/deprecate", summary="弃用Skill版本")
async def deprecate_skill_version(
    skill_id: int,
    version_id: int,
    req: DeprecateVersionRequest,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:update")),
):
    try:
        data = await skill_service.deprecate_version(
            session, skill_id, version_id, req.sunset_date
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或版本不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "Skill 版本已弃用", "data": data}


@router.post(
    "/{skill_id}/versions/{version_id}/ai-policies-audits",
    summary="发起Skill版本安全审查",
)
async def create_skill_version_ai_policies_audit(
    skill_id: int,
    version_id: int,
    policy: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("ai_policies:scan")),
):
    try:
        data = await ai_policies_service.create_skill_audit(
            session, skill_id, current_user, version_id=version_id, policy=policy
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或版本不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "审查任务已创建", "data": data}


@router.post(
    "/{skill_id}/versions/{version_id}/drift-check",
    summary="立即检测版本漂移",
)
async def check_skill_version_drift(
    skill_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:update")),
):
    """重新拉取 url 源内容并比对 hash，回写 drift 字段。ZIP 模式版本返回 400。"""
    try:
        data = await skill_drift_service.check_single_drift(session, version_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或版本不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "漂移检测完成", "data": data}


@router.post(
    "/{skill_id}/versions/{version_id}/resync",
    summary="重新同步漂移版本",
)
async def resync_skill_version(
    skill_id: int,
    version_id: int,
    req: ResyncVersionRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:update")),
):
    """把漂移版本当前源内容作为新版本入库（inactive + 未审查，需后续审查→激活）。"""
    try:
        data = await skill_drift_service.resync_as_new_version(
            session,
            version_id,
            new_version=req.new_version,
            created_by=current_user["id"],
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或版本不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "code": 200,
        "message": "已创建新版本，请完成安全审查后再激活",
        "data": data,
    }


@router.post("/{skill_id}/versions/{version_id}/yank", summary="撤回Skill版本")
async def yank_skill_version(
    skill_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:update")),
):
    """撤回已发布版本（published→yanked），命中当前指针则重算次新 published。"""
    try:
        data = await skill_service.yank_version(session, skill_id, version_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或版本不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"code": 200, "message": "Skill 版本已撤回", "data": data}


@router.post("/{skill_id}/versions/{version_id}/restore", summary="恢复Skill版本")
async def restore_skill_version(
    skill_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:update")),
):
    """恢复已撤回版本（yanked→published），恢复后可再次设为激活。"""
    try:
        data = await skill_service.restore_version(session, skill_id, version_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或版本不存在")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "Skill 版本已恢复", "data": data}


@router.put("/{skill_id}/hidden", summary="切换Skill治理下架")
async def set_skill_hidden(
    skill_id: int,
    req: SetHiddenRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:update")),
):
    """治理下架 overlay（hidden），独立于发布开关与可见性。"""
    try:
        data = await skill_service.set_hidden(
            session, skill_id, req.hidden, current_user["id"]
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "治理下架状态已更新", "data": data}


@router.post("", summary="创建 Skill")
async def create_skill(
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
    is_published: bool = Form(False),
    requires_approval: bool = Form(False),
    visibility_type: str = Form("all"),
    source_url: str = Form(""),
    zip_file: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:create")),
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
        is_published=is_published,
        requires_approval=requires_approval,
        visibility_type=visibility_type,
        zip_content=zip_content,
        zip_filename=zip_filename,
        source_url=source_url or None,
        created_by=current_user["id"],
    )
    return {"code": 200, "message": "Skill 创建成功", "data": data}


@router.put("/{skill_id}", summary="更新 Skill")
async def update_skill(
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
    is_active: bool | None = Form(None),
    is_published: bool | None = Form(None),
    requires_approval: bool | None = Form(None),
    visibility_type: str | None = Form(None),
    zip_file: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:update")),
):
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
    if is_active is not None:
        kwargs["is_active"] = is_active
    if is_published is not None:
        kwargs["is_published"] = is_published
    if requires_approval is not None:
        kwargs["requires_approval"] = requires_approval
    if visibility_type is not None:
        kwargs["visibility_type"] = visibility_type

    zip_content = None
    zip_filename = None
    if zip_file is not None and zip_file.filename:
        zip_content = await zip_file.read()
        zip_filename = zip_file.filename

    try:
        data = await skill_service.update_skill(
            session,
            skill_id,
            actor_id=current_user["id"],
            zip_content=zip_content,
            zip_filename=zip_filename,
            **kwargs,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "Skill 更新成功", "data": data}


@router.delete("/{skill_id}", summary="删除 Skill")
async def delete_skill(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("skill:delete")),
):
    try:
        await skill_service.delete_skill(session, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "Skill 删除成功", "data": None}


@router.get("/{skill_id}/download")
async def download_skill(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("skill:read")),
):
    try:
        zip_path, download_name, _ = await skill_service.get_skill_zip(
            session, skill_id
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或 zip 文件不存在")
    await skill_service.record_skill_usage(
        session, user_id=current_user["id"], skill_id=skill_id, action="download"
    )
    return FileResponse(zip_path, filename=download_name, media_type="application/zip")


@router.post("/{skill_id}/ai-policies-audits", summary="发起 Skill 安全审查")
async def create_skill_ai_policies_audit(
    skill_id: int,
    policy: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("ai_policies:scan")),
):
    try:
        data = await ai_policies_service.create_skill_audit(
            session, skill_id, current_user, policy=policy
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "message": "审查任务已创建", "data": data}


@router.get("/{skill_id}/install-info")
async def get_install_info(
    skill_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        data = await skill_service.get_install_info(
            session,
            skill_id,
            user_id=current_user["id"],
            base_url_override=resolve_platform_public_url(request),
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"code": 200, "message": "ok", "data": data}


@router.get("/{skill_id}/zip", summary="Agent 下载 Skill zip")
async def get_skill_zip_public(
    skill_id: int,
    session: AsyncSession = Depends(get_db),
    identity: dict = Depends(get_ai_key_identity),
):
    """Agent 下载端点，通过 AI Key 认证。仅已发布的 Skill 可下载。"""
    try:
        zip_path, download_name, _ = await skill_service.get_skill_zip(
            session, skill_id, require_published=True
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Skill 或 zip 文件不存在")

    # 权限检查：需审批的 Skill 必须在 Key 的 skills 列表中
    skill_data = await skill_service.get_skill(session, skill_id)
    if skill_data.get("requires_approval"):
        if skill_id not in identity["skills"]:
            raise HTTPException(status_code=403, detail="请先申请使用该 Skill")

    await skill_service.record_skill_usage(
        session,
        user_id=identity["user_id"],
        skill_id=skill_id,
        action="agent_download",
        ai_key_id=identity["ai_key_id"],
    )
    return FileResponse(zip_path, filename=download_name, media_type="application/zip")
