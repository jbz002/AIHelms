"""MCP 授权中心：把 mcp_grants 编译成每把 key 的物化授权，并下发给网关。

分层（`03` §4）：

    mcp_grants（事实源） → 编译 → ai_keys.mcps / mcp_tools / mcp_toolsets（物化）
                        → 下发 → LiteLLM object_permission（执行）

编译规则（P1，逐条对应 `03` §4.1）：

- 主体集合：public 恒在；主 Key 另加 user:<owner>、role:<其角色>、dept:<其部门>。
- 命中 server 级 allow → 该 server 不限工具；只被 toolset 命中的 server → 只给 toolset
  里、且已过审的工具（**只要同时有 server 级 allow，toolset 就不再收窄**——与计划口径一致）。
- deny 优先：任一命中的 server 级 deny 把该 server 摘掉（P1 只支持 server 级 deny）。
- 再与「已发布 + 进网关」和「工具已过审」求交；工具被过滤到空 → 整个 server 摘掉。

P1 只编译主 Key（personal_main / dept_main / project_main）：场景 Key 的 `mcps` 是
管理员有意的窄化，继续手工维护，不参与编译。
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import McpServer, McpTool, McpToolset, UserDepartment, UserRole
from repositories import mcp_authz_repo
from services import litellm_client

logger = logging.getLogger(__name__)

MAIN_KEY_TYPES = ("personal_main", "dept_main", "project_main")


@dataclass(frozen=True)
class GrantView:
    subject_type: str
    subject_id: int | None
    target_type: str
    target_id: int
    effect: str


@dataclass
class CompiledGrants:
    server_ids: list[int] = field(default_factory=list)
    servers: list[str] = field(default_factory=list)
    tool_permissions: dict[str, list[str]] = field(default_factory=dict)
    toolsets: list[str] = field(default_factory=list)
    policy_hash: str = ""

    def payload(self) -> dict:
        return {
            "server_ids": self.server_ids,
            "servers": self.servers,
            "tool_permissions": self.tool_permissions,
            "toolsets": self.toolsets,
        }


def _hash_payload(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compile_grants(
    grants: list[GrantView],
    subjects: set[tuple[str, int | None]],
    *,
    server_names: dict[int, str],
    published_ids: set[int],
    public_ids: set[int],
    approved_tools: dict[int, set[str]],
    toolset_items: dict[int, set[tuple[int, str]]],
    toolset_names: dict[int, str],
) -> CompiledGrants:
    """纯函数：给定授权与资源事实，算出这把 key 的目标授权（无 IO，便于单测）。"""
    denied: set[int] = set()
    server_level: set[int] = set()
    toolset_tools: dict[int, set[str]] = {}
    used_toolsets: set[int] = set()

    for grant in grants:
        if (grant.subject_type, grant.subject_id) not in subjects:
            continue
        if grant.target_type == "server":
            if grant.effect == "deny":
                denied.add(grant.target_id)
            else:
                server_level.add(grant.target_id)
        elif grant.target_type == "toolset" and grant.effect == "allow":
            used_toolsets.add(grant.target_id)
            for server_id, tool_name in toolset_items.get(grant.target_id, set()):
                toolset_tools.setdefault(server_id, set()).add(tool_name)

    candidates = (server_level | set(toolset_tools) | public_ids) - denied
    server_ids: list[int] = []
    servers: list[str] = []
    tool_permissions: dict[str, list[str]] = {}

    for server_id in sorted(candidates):
        if server_id not in published_ids:
            continue
        name = server_names.get(server_id)
        if not name:
            continue
        if server_id in server_level or server_id in public_ids:
            # 公共 server 对所有 key 是「整个 server 可用」，等同 server 级授权，
            # 不被 toolset 收窄（与「所有命中都是 server 级 → 不限工具」口径一致）。
            tools = None
        else:
            allowed = approved_tools.get(server_id, set())
            tools = {t for t in toolset_tools.get(server_id, set()) if t in allowed}
            if not tools:
                continue  # 工具被过滤到空 → 整个 server 不可见
        server_ids.append(server_id)
        servers.append(name)
        if tools is not None:
            tool_permissions[name] = sorted(tools)

    compiled = CompiledGrants(
        server_ids=server_ids,
        servers=servers,
        tool_permissions=tool_permissions,
        toolsets=sorted(toolset_names[t] for t in used_toolsets if t in toolset_names),
    )
    compiled.policy_hash = _hash_payload(
        {
            "servers": compiled.servers,
            "tools": compiled.tool_permissions,
            "toolsets": compiled.toolsets,
        }
    )
    return compiled


async def _subjects_for_key(session: AsyncSession, key) -> set[tuple[str, int | None]]:
    subjects: set[tuple[str, int | None]] = {("public", None)}
    if key.owner_type == "user":
        subjects.add(("user", key.owner_id))
        roles = await session.execute(
            select(UserRole.role_id).where(UserRole.user_id == key.owner_id)
        )
        subjects.update(("role", rid) for (rid,) in roles.all())
        depts = await session.execute(
            select(UserDepartment.department_id).where(
                UserDepartment.user_id == key.owner_id
            )
        )
        subjects.update(("dept", did) for (did,) in depts.all())
    elif key.owner_type == "department":
        subjects.add(("dept", key.owner_id))
    return subjects


@dataclass
class CompileContext:
    server_names: dict[int, str]
    published_ids: set[int]
    public_ids: set[int]
    approved_tools: dict[int, set[str]]
    toolset_items: dict[int, set[tuple[int, str]]]
    toolset_names: dict[int, str]


async def load_context(session: AsyncSession) -> CompileContext:
    servers = list((await session.execute(select(McpServer))).scalars().all())
    server_names = {s.id: s.server_name for s in servers}
    published_ids = {
        s.id
        for s in servers
        if s.is_published and not s.requires_approval and s.sync_to_litellm
    }
    public_ids = {s.id for s in servers if s.is_public and s.id in published_ids}

    approved: dict[int, set[str]] = {}
    tools = (
        await session.execute(
            select(McpTool).where(McpTool.is_active == True)  # noqa: E712
        )
    ).scalars()
    for tool in tools:
        if tool.review_status != "approved":
            continue
        approved.setdefault(tool.server_id, set()).add(tool.tool_name)

    toolsets = list((await session.execute(select(McpToolset))).scalars().all())
    toolset_items: dict[int, set[tuple[int, str]]] = {}
    toolset_names: dict[int, str] = {}
    for toolset in toolsets:
        toolset_names[toolset.id] = toolset.name
        items: set[tuple[int, str]] = set()
        for item in toolset.items or []:
            if not isinstance(item, dict):
                continue
            server_id = item.get("server_id")
            tool_name = item.get("tool_name")
            if isinstance(server_id, int) and isinstance(tool_name, str):
                items.add((server_id, tool_name))
        toolset_items[toolset.id] = items

    return CompileContext(
        server_names=server_names,
        published_ids=published_ids,
        public_ids=public_ids,
        approved_tools=approved,
        toolset_items=toolset_items,
        toolset_names=toolset_names,
    )


async def compile_key(
    session: AsyncSession, key, context: CompileContext | None = None
) -> CompiledGrants:
    if key.key_type not in MAIN_KEY_TYPES:
        raise ValueError("P1 只编译主 Key；场景 Key 的 mcps 由管理员手工维护")
    context = context or await load_context(session)
    subjects = await _subjects_for_key(session, key)
    grants = await mcp_authz_repo.find_grants_for_subjects(
        session, sorted(subjects, key=lambda s: (s[0], s[1] or 0))
    )
    views = [
        GrantView(
            subject_type=g.subject_type,
            subject_id=g.subject_id,
            target_type=g.target_type,
            target_id=g.target_id,
            effect=g.effect,
        )
        for g in grants
    ]
    return compile_grants(
        views,
        subjects,
        server_names=context.server_names,
        published_ids=context.published_ids,
        public_ids=context.public_ids,
        approved_tools=context.approved_tools,
        toolset_items=context.toolset_items,
        toolset_names=context.toolset_names,
    )


async def apply_compiled(
    session: AsyncSession, key, compiled: CompiledGrants, *, push: bool = True
) -> dict:
    """把编译产物写进 ai_keys 并（可选）下发；幂等（内容相同则不重复写网关）。"""
    from services import ai_key_service

    changed = (
        list(key.mcps or []) != compiled.server_ids
        or dict(key.mcp_tools or {}) != compiled.tool_permissions
        or list(key.mcp_toolsets or []) != compiled.toolsets
    )
    if changed:
        key.mcps = compiled.server_ids
        key.mcp_tools = compiled.tool_permissions
        key.mcp_toolsets = compiled.toolsets
    key.mcp_policy_hash = compiled.policy_hash

    result = {"key_id": key.id, "changed": changed, "pushed": False, "error": None}
    if not push or not key.litellm_key_id:
        await mcp_authz_repo.upsert_sync_state(
            session, key.id, input_hash=compiled.policy_hash, status="pending"
        )
        return result

    payload = await ai_key_service.build_object_permission(
        session, compiled.server_ids, compiled.tool_permissions
    )
    try:
        await litellm_client.update_key(
            key_id=key.litellm_key_id, object_permission=payload
        )
    except litellm_client.LiteLLMError as exc:
        await mcp_authz_repo.upsert_sync_state(
            session,
            key.id,
            input_hash=compiled.policy_hash,
            status="error",
            error_code=str(exc)[:64],
        )
        result["error"] = str(exc)
        logger.warning("mcp authz push failed for key %s: %s", key.id, exc)
        return result

    await mcp_authz_repo.upsert_sync_state(
        session,
        key.id,
        input_hash=compiled.policy_hash,
        applied_hash=compiled.policy_hash,
        status="synced",
    )
    result["pushed"] = True
    return result


async def sync_key(
    session: AsyncSession,
    key,
    context: CompileContext | None = None,
    *,
    push: bool = True,
) -> dict:
    compiled = await compile_key(session, key, context)
    return await apply_compiled(session, key, compiled, push=push)


async def sync_keys_for_subject(
    session: AsyncSession,
    subject_type: str,
    subject_id: int | None,
    *,
    push: bool = True,
    changed_by: int | None = None,
    summary: str = "",
) -> dict:
    """某主体（user/dept/role/public）的授权变了：重编译受影响的 key。"""
    context = await load_context(session)
    keys = await _keys_for_subject(session, subject_type, subject_id)
    applied = 0
    failed = 0
    for key in keys:
        if key.key_type not in MAIN_KEY_TYPES or not key.litellm_key_id:
            continue
        try:
            result = await sync_key(session, key, context, push=push)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("recompile key %s failed: %s", key.id, exc)
            continue
        if result.get("pushed") or result.get("changed"):
            applied += 1
    await mcp_authz_repo.bump_policy_version(
        session, changed_by, summary or f"{subject_type}:{subject_id} 授权变更"
    )
    return {"keys": len(keys), "applied": applied, "failed": failed}


async def sync_all_keys(
    session: AsyncSession,
    *,
    push: bool = True,
    changed_by: int | None = None,
    summary: str = "",
) -> dict:
    """全量重编译（server 发布/下线、工具审核、工具束内容变更后调用）。"""
    from models.db import AiKey

    context = await load_context(session)
    keys = list((await session.execute(select(AiKey))).scalars().all())
    applied = 0
    failed = 0
    for key in keys:
        if key.key_type not in MAIN_KEY_TYPES or not key.litellm_key_id:
            continue
        try:
            result = await sync_key(session, key, context, push=push)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("recompile key %s failed: %s", key.id, exc)
            continue
        if result.get("pushed") or result.get("changed"):
            applied += 1
    await mcp_authz_repo.bump_policy_version(
        session, changed_by, summary or "全量重编译"
    )
    return {"keys": len(keys), "applied": applied, "failed": failed}


async def _keys_for_subject(
    session: AsyncSession, subject_type: str, subject_id: int | None
) -> list:
    from models.db import AiKey

    if subject_type == "user":
        return list(
            (
                await session.execute(
                    select(AiKey).where(
                        AiKey.owner_type == "user", AiKey.owner_id == subject_id
                    )
                )
            )
            .scalars()
            .all()
        )
    if subject_type == "public":
        return list((await session.execute(select(AiKey))).scalars().all())
    if subject_type == "dept":
        return list(
            (
                await session.execute(
                    select(AiKey).where(
                        AiKey.owner_type == "department",
                        AiKey.owner_id == subject_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    if subject_type == "role":
        user_ids = [
            uid
            for (uid,) in (
                await session.execute(
                    select(UserRole.user_id).where(UserRole.role_id == subject_id)
                )
            ).all()
        ]
        if not user_ids:
            return []
        return list(
            (
                await session.execute(
                    select(AiKey).where(
                        AiKey.owner_type == "user", AiKey.owner_id.in_(user_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
    return []


def _normalize_tools(raw) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): sorted(tools)
        for name, tools in raw.items()
        if isinstance(tools, list)
    }


def _find_in_info(node, key):
    if isinstance(node, dict):
        if isinstance(node.get(key), (list, dict)):
            return node[key]
        for value in node.values():
            found = _find_in_info(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_in_info(value, key)
            if found is not None:
                return found
    return None


async def reconcile_all(session: AsyncSession, *, apply: bool = False) -> dict:
    """对账：AIHelms 期望的 object_permission vs LiteLLM 现状（公共 server 不计差异）。"""
    from models.db import AiKey
    from repositories import mcp_repo
    from services import ai_key_service

    public_names = set(await mcp_repo.find_public_server_names(session))
    keys = list(
        (
            await session.execute(
                select(AiKey).where(AiKey.litellm_key_id.isnot(None)).order_by(AiKey.id)
            )
        )
        .scalars()
        .all()
    )
    drift_items: list[dict] = []
    errors = 0
    fixed = 0
    for key in keys:
        expected = await ai_key_service.build_object_permission(
            session, key.mcps or [], getattr(key, "mcp_tools", None)
        )
        exp_servers = set(expected.get("mcp_servers") or []) - public_names
        exp_tools = _normalize_tools(expected.get("mcp_tool_permissions"))
        try:
            info = await litellm_client.get_key_info(key.litellm_key_id)
        except litellm_client.LiteLLMError as exc:
            errors += 1
            drift_items.append({"key_id": key.id, "error": str(exc)})
            continue
        act_servers = set(_find_in_info(info, "mcp_servers") or []) - public_names
        act_tools = {
            name: tools
            for name, tools in _normalize_tools(
                _find_in_info(info, "mcp_tool_permissions")
            ).items()
            if name not in public_names
        }
        if exp_servers == act_servers and exp_tools == act_tools:
            continue
        item = {
            "key_id": key.id,
            "added": sorted(exp_servers - act_servers),
            "removed": sorted(act_servers - exp_servers),
            "tools_expected": exp_tools,
            "tools_actual": act_tools,
        }
        drift_items.append(item)
        if apply:
            try:
                await litellm_client.update_key(
                    key_id=key.litellm_key_id, object_permission=expected
                )
                fixed += 1
                item["fixed"] = True
            except litellm_client.LiteLLMError as exc:
                errors += 1
                item["fix_error"] = str(exc)

    return {
        "keys": len(keys),
        "drift": len(drift_items),
        "fixed": fixed,
        "errors": errors,
        "items": drift_items[:50],
        "mode": "apply" if apply else "check",
    }
