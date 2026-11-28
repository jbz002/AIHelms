"""MCP 授权中心 API：授权矩阵、工具束、工具元数据、对账（P1）。

事实源是 `mcp_grants`；`ai_keys.mcps/mcp_tools` 是编译产物，LiteLLM 的
`object_permission` 是下发结果。写接口在 `mcp_authz_compile_enabled` 打开时
同步重编译受影响的 key；关闭时只记策略版本（观察模式）。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.deps import get_db, require_permission
from models.db import Department, McpGrant, McpToolset, Role, User
from repositories import mcp_authz_repo, mcp_repo
from services import mcp_authz_service

router = APIRouter(prefix="/mcp", tags=["mcp"])


class GrantCreateRequest(BaseModel):
    subject_type: str = Field(..., pattern="^(user|dept|role|public)$")
    subject_id: int | None = Field(None, ge=1)
    target_type: str = Field(..., pattern="^(server|toolset)$")
    target_id: int = Field(..., ge=1)
    effect: str = Field("allow", pattern="^(allow|deny)$")
    expires_at: datetime | None = None
    reason: str = Field("", max_length=500)


class ToolsetItem(BaseModel):
    server_id: int = Field(..., ge=1)
    tool_name: str = Field(..., min_length=1, max_length=200)


class ToolsetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=500)
    items: list[ToolsetItem] = Field(default_factory=list)


class ReconcileRequest(BaseModel):
    mode: str = Field("check", pattern="^(check|apply)$")


class ToolMetadataRequest(BaseModel):
    risk_level: str | None = Field(None, pattern="^(read|write|sensitive|destructive)$")
    data_classification: str | None = Field(
        None, pattern="^(public|internal|confidential|secret)$"
    )
    permission_key: str | None = Field(None, max_length=100)
    fields_allowlist: list[str] | None = None
    annotations: dict | None = None
    review_status: str | None = Field(None, pattern="^(pending|approved|rejected)$")


async def _operator_names(
    session: AsyncSession, grants: list[McpGrant]
) -> dict[int, str]:
    """一次查出本页涉及的授予人/撤销人姓名，供审计列展示。"""
    ids = {g.granted_by for g in grants if g.granted_by} | {
        g.revoked_by for g in grants if g.revoked_by
    }
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(User.id, User.display_name, User.username).where(User.id.in_(ids))
        )
    ).all()
    return {row[0]: (row[1] or row[2] or str(row[0])) for row in rows}


def _serialize_grant(grant: McpGrant, operators: dict[int, str] | None = None) -> dict:
    operators = operators or {}
    return {
        "id": grant.id,
        "subject_type": grant.subject_type,
        "subject_id": grant.subject_id,
        "target_type": grant.target_type,
        "target_id": grant.target_id,
        "effect": grant.effect,
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "granted_by": grant.granted_by,
        "granted_by_name": operators.get(grant.granted_by) if grant.granted_by else None,
        "reason": grant.reason,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "revoked_by": grant.revoked_by,
        "revoked_by_name": operators.get(grant.revoked_by) if grant.revoked_by else None,
        "created_at": grant.created_at.isoformat() if grant.created_at else None,
    }


def _serialize_toolset(toolset: McpToolset) -> dict:
    return {
        "id": toolset.id,
        "name": toolset.name,
        "description": toolset.description,
        "items": toolset.items or [],
        "created_by": toolset.created_by,
        "created_at": toolset.created_at.isoformat() if toolset.created_at else None,
    }


async def _after_grant_change(
    session: AsyncSession,
    subject_type: str,
    subject_id: int | None,
    current_user: dict,
    summary: str,
) -> dict:
    """授权变更后的收尾：编译下发或只记版本（观察模式），并提交事务。"""
    if settings.mcp_authz_compile_enabled:
        result = await mcp_authz_service.sync_keys_for_subject(
            session,
            subject_type,
            subject_id,
            push=True,
            changed_by=current_user["id"],
            summary=summary,
        )
        result["mode"] = "compiled"
    else:
        await mcp_authz_repo.bump_policy_version(
            session, current_user["id"], f"{summary}（观察模式，未下发）"
        )
        result = {"mode": "observe"}
    await session.commit()
    return result


async def _validate_subject(session: AsyncSession, subject_type: str, subject_id):
    if subject_type == "public":
        return
    if subject_id is None:
        raise HTTPException(status_code=400, detail="该主体类型必须指定 subject_id")
    model = {"user": User, "dept": Department, "role": Role}[subject_type]
    if await session.get(model, subject_id) is None:
        raise HTTPException(status_code=404, detail="授权主体不存在")


async def _validate_target(session: AsyncSession, target_type: str, target_id: int):
    if target_type == "server":
        if await mcp_repo.find_server_by_id(session, target_id) is None:
            raise HTTPException(status_code=404, detail="MCP Server 不存在")
    elif await mcp_authz_repo.find_toolset_by_id(session, target_id) is None:
        raise HTTPException(status_code=404, detail="工具束不存在")


# ─── 授权矩阵 ────────────────────────────────────────────────────────────────


@router.get("/grants", summary="授权矩阵列表")
async def list_grants(
    subject_type: str | None = None,
    subject_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    include_revoked: bool = False,
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("mcp:read")),
):
    grants = await mcp_authz_repo.list_grants(
        session,
        subject_type=subject_type,
        subject_id=subject_id,
        target_type=target_type,
        target_id=target_id,
        include_revoked=include_revoked,
    )
    operators = await _operator_names(session, grants)
    items = [_serialize_grant(g, operators) for g in grants]
    return {"code": 200, "data": {"items": items}}


@router.post("/grants", summary="新增授权")
async def create_grant(
    req: GrantCreateRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:update")),
):
    if req.effect == "deny" and req.target_type == "toolset":
        # P1 只支持 server 级 deny：工具束级 deny 的语义（拒整束还是拒其中工具）
        # 留到 P2 与差量策略一起定义，现在拒绝掉避免误解。
        raise HTTPException(status_code=400, detail="P1 只支持 server 级 deny")
    await _validate_subject(session, req.subject_type, req.subject_id)
    await _validate_target(session, req.target_type, req.target_id)

    existing = await mcp_authz_repo.find_active_grant(
        session, req.subject_type, req.subject_id, req.target_type, req.target_id
    )
    if existing:
        raise HTTPException(
            status_code=409, detail=f"该主体对此目标已有生效授权（id={existing.id}）"
        )

    grant = await mcp_authz_repo.create_grant(
        session,
        McpGrant(
            subject_type=req.subject_type,
            subject_id=req.subject_id,
            target_type=req.target_type,
            target_id=req.target_id,
            effect=req.effect,
            expires_at=req.expires_at,
            granted_by=current_user["id"],
            reason=req.reason,
        ),
    )
    summary = (
        f"新增授权 {req.subject_type}:{req.subject_id} -> "
        f"{req.target_type}:{req.target_id} ({req.effect})"
    )
    result = await _after_grant_change(
        session, req.subject_type, req.subject_id, current_user, summary
    )
    return {
        "code": 200,
        "message": (
            "授权已生效" if result["mode"] == "compiled" else "授权已登记（观察模式）"
        ),
        "data": {"grant": _serialize_grant(grant), "sync": result},
    }


@router.delete("/grants/{grant_id}", summary="撤销授权")
async def revoke_grant(
    grant_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:update")),
):
    grant = await session.get(McpGrant, grant_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="授权记录不存在")
    if grant.revoked_at is not None:
        return {"code": 200, "message": "该授权已撤销", "data": None}
    await mcp_authz_repo.revoke_grant(session, grant, revoked_by=current_user["id"])
    summary = (
        f"撤销授权 {grant.subject_type}:{grant.subject_id} -> "
        f"{grant.target_type}:{grant.target_id}（{grant.effect}）"
    )
    result = await _after_grant_change(
        session, grant.subject_type, grant.subject_id, current_user, summary
    )
    return {
        "code": 200,
        "message": (
            "授权已撤销" if result["mode"] == "compiled" else "撤销已登记（观察模式）"
        ),
        "data": {"sync": result},
    }


# ─── 工具束 ──────────────────────────────────────────────────────────────────


@router.get("/toolsets", summary="工具束列表")
async def list_toolsets(
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("mcp:read")),
):
    toolsets = await mcp_authz_repo.list_toolsets(session)
    return {
        "code": 200,
        "data": {"items": [_serialize_toolset(t) for t in toolsets]},
    }


@router.post("/toolsets", summary="创建工具束")
async def create_toolset(
    req: ToolsetCreateRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:update")),
):
    if await mcp_authz_repo.find_toolset_by_name(session, req.name):
        raise HTTPException(status_code=409, detail="工具束名称已存在")
    items = []
    for item in req.items:
        server = await mcp_repo.find_server_by_id(session, item.server_id)
        if server is None:
            raise HTTPException(
                status_code=400, detail=f"MCP Server 不存在: {item.server_id}"
            )
        tools = await mcp_repo.find_tools_by_server(session, item.server_id)
        if not any(t.tool_name == item.tool_name for t in tools):
            raise HTTPException(
                status_code=400,
                detail=f"工具不存在: {server.server_name}.{item.tool_name}",
            )
        items.append({"server_id": item.server_id, "tool_name": item.tool_name})

    toolset = await mcp_authz_repo.create_toolset(
        session,
        McpToolset(
            name=req.name,
            description=req.description,
            items=items,
            created_by=current_user["id"],
        ),
    )
    await session.commit()
    return {
        "code": 200,
        "message": "工具束已创建",
        "data": _serialize_toolset(toolset),
    }


@router.delete("/toolsets/{toolset_id}", summary="删除工具束")
async def delete_toolset(
    toolset_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:delete")),
):
    toolset = await mcp_authz_repo.find_toolset_by_id(session, toolset_id)
    if toolset is None:
        raise HTTPException(status_code=404, detail="工具束不存在")
    active = await mcp_authz_repo.list_grants(
        session, target_type="toolset", target_id=toolset_id
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"仍有 {len(active)} 条生效授权引用该工具束，请先撤销授权",
        )
    await mcp_authz_repo.delete_toolset(session, toolset)
    await session.commit()
    return {"code": 200, "message": "工具束已删除", "data": None}


# ─── 对账 ────────────────────────────────────────────────────────────────────


@router.post("/reconcile", summary="授权对账（check/apply）")
async def reconcile(
    req: ReconcileRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:read")),
):
    result = await mcp_authz_service.reconcile_all(session, apply=req.mode == "apply")
    await session.commit()
    return {"code": 200, "data": result}


# ─── 工具元数据 ──────────────────────────────────────────────────────────────


@router.put("/servers/{server_id}/tools/{tool_id}/metadata", summary="更新工具元数据")
async def update_tool_metadata(
    server_id: int,
    tool_id: int,
    req: ToolMetadataRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("mcp:update")),
):
    tool = await mcp_repo.find_tool_by_id(session, tool_id)
    if tool is None or tool.server_id != server_id:
        raise HTTPException(status_code=404, detail="工具不存在或不属于该 Server")

    # 公共 server 对所有 Key 无条件放行：把其中任一工具标成非只读等于绕过授权矩阵。
    # 必须在改动之前判（改动后再 rollback 会让 ORM 实例过期，读属性触发 MissingGreenlet）。
    new_risk = req.risk_level if req.risk_level is not None else tool.risk_level
    if (new_risk or "read") != "read":
        server = await mcp_repo.find_server_by_id(session, server_id)
        if server is not None and server.is_public:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"该 Server 已开启公共授权（全员可用），工具「{tool.tool_name}」"
                    "不能标记为非只读。请先关闭公共授权，改用授权矩阵按人/角色授权"
                ),
            )

    changes = []
    for field in (
        "risk_level",
        "data_classification",
        "permission_key",
        "fields_allowlist",
        "annotations",
        "review_status",
    ):
        value = getattr(req, field)
        if value is not None and getattr(tool, field) != value:
            setattr(tool, field, value)
            changes.append(field)
    if "review_status" in changes:
        tool.reviewed_by = current_user["id"]
        tool.reviewed_at = datetime.now()

    await session.flush()

    sync = {"mode": "skipped", "reason": "元数据未变化"}
    if changes:
        if settings.mcp_authz_compile_enabled:
            sync = await mcp_authz_service.sync_all_keys(
                session,
                push=True,
                changed_by=current_user["id"],
                summary=f"工具元数据变更 {tool.tool_key or tool.tool_name}: {changes}",
            )
            sync["mode"] = "compiled"
        else:
            await mcp_authz_repo.bump_policy_version(
                session,
                current_user["id"],
                f"工具元数据变更 {tool.tool_key or tool.tool_name}: {changes}（观察模式）",
            )
            sync = {"mode": "observe", "changes": changes}
    await session.commit()
    return {
        "code": 200,
        "message": "工具元数据已更新",
        "data": {
            "id": tool.id,
            "tool_name": tool.tool_name,
            "tool_key": tool.tool_key,
            "risk_level": tool.risk_level,
            "data_classification": tool.data_classification,
            "review_status": tool.review_status,
            "changes": changes,
            "sync": sync,
        },
    }
