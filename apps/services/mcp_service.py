import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, NotFoundError, ValidationError
from models.db import McpServer, McpServerVersion, McpTool
from repositories import mcp_repo, mcp_version_repo
from services import litellm_client, versioning_service
from services.litellm_client import LiteLLMError

logger = logging.getLogger(__name__)


def to_litellm_transport(transport: str) -> str:
    """LiteLLM 只支持 sse/http/stdio，streamableHttp 变体统一映射为 http。"""
    return "http" if transport in ("streamableHttp", "streamable_http") else transport


# ─── MCP Server CRUD ─────────────────────────────────────────────────────────


async def list_servers(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    category: str | None = None,
    is_active: bool | None = None,
    is_published: bool | None = None,
    status: str | None = None,
) -> dict:
    total = await mcp_repo.count_servers(
        session, category, is_active, is_published, status
    )
    items = await mcp_repo.find_all_servers(
        session, page, page_size, category, is_active, is_published, status
    )
    return {
        "items": [_serialize_server(s) for s in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_server(session: AsyncSession, server_id: int) -> dict:
    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server:
        raise NotFoundError("mcp_server", server_id)
    data = _serialize_server(server)
    tools = await mcp_repo.find_tools_by_server(session, server_id)
    data["tools"] = [_serialize_tool(t) for t in tools]
    return data


async def create_server(
    session: AsyncSession,
    name: str,
    server_name: str,
    url: str,
    transport: str = "sse",
    auth_type: str = "none",
    credentials: dict | None = None,
    description: str = "",
    instructions: str = "",
    mcp_info: dict | None = None,
    extra_headers: list[str] | None = None,
    allowed_tools: list | None = None,
    authorization_url: str | None = None,
    token_url: str | None = None,
    registration_url: str | None = None,
    category: str = "general",
    tags: list | None = None,
    author: str = "",
    icon_url: str = "",
    documentation_url: str = "",
    source_url: str = "",
    billing_type: str = "per_call",
    internal_cost_per_call: float = 0,
    external_cost_per_call: float = 0,
    is_published: bool = False,
    visibility_type: str = "all",
    requires_approval: bool = False,
    created_by: int | None = None,
) -> dict:
    if transport not in ("sse", "http", "streamable_http", "streamableHttp"):
        raise ValidationError("transport 只支持 sse 或 streamableHttp")

    if "-" in server_name:
        raise ValidationError(
            "server_name 不能包含 '-'（LiteLLM 限制），请使用 '_' 替代"
        )

    existing = await mcp_repo.find_server_by_name(session, server_name)
    if existing:
        raise ConflictError(f"MCP Server 名称 '{server_name}' 已存在")

    sid = str(uuid.uuid4())
    server = McpServer(
        server_id=sid,
        name=name,
        server_name=server_name,
        url=url,
        transport=transport,
        auth_type=auth_type,
        credentials=credentials or {},
        description=description,
        instructions=instructions,
        mcp_info=mcp_info or {},
        extra_headers=extra_headers or [],
        allowed_tools=allowed_tools or [],
        authorization_url=authorization_url,
        token_url=token_url,
        registration_url=registration_url,
        category=category,
        tags=tags or [],
        author=author,
        icon_url=icon_url,
        documentation_url=documentation_url,
        source_url=source_url,
        billing_type=billing_type,
        internal_cost_per_call=internal_cost_per_call,
        external_cost_per_call=external_cost_per_call,
        is_published=is_published,
        visibility_type=visibility_type,
        requires_approval=requires_approval,
        created_by=created_by,
    )
    server = await mcp_repo.create_server(session, server)
    await session.flush()

    try:
        await _sync_server_to_litellm(server)
    except LiteLLMError as e:
        await session.rollback()
        logger.error("sync mcp server to litellm failed: %s", str(e))
        raise ValidationError("保存失败，服务器内部错误")

    await session.commit()
    await session.refresh(server)

    # 创建后自动同步工具列表
    try:
        await refresh_tools(session, server.id)
    except (ValidationError, LiteLLMError):
        pass  # 工具同步失败不影响创建

    # 为新 Server 种入 v1 active 版本（与存量回填一致）
    v1 = McpServerVersion(
        server_id=server.id,
        version="1.0.0",
        is_active=True,
        lifecycle_status="active",
        source="manual",
        url=server.url,
        transport=server.transport,
        auth_type=server.auth_type,
        credentials=server.credentials or {},
        mcp_info=server.mcp_info or {},
        allowed_tools=server.allowed_tools or [],
        extra_headers=server.extra_headers or [],
        instructions=server.instructions,
        change_log="initial version",
        created_by=created_by,
    )
    v1 = await mcp_version_repo.create(session, v1)
    server.current_version_id = v1.id
    await session.commit()
    await session.refresh(server)

    return _serialize_server(server)


async def update_server(
    session: AsyncSession,
    server_id: int,
    **kwargs,
) -> dict:
    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server:
        raise NotFoundError("mcp_server", server_id)

    if "transport" in kwargs and kwargs["transport"] not in (
        "sse",
        "http",
        "streamable_http",
        "streamableHttp",
    ):
        raise ValidationError("transport 只支持 sse 或 streamableHttp")

    if "server_name" in kwargs and kwargs["server_name"] != server.server_name:
        if "-" in kwargs["server_name"]:
            raise ValidationError(
                "server_name 不能包含 '-'（LiteLLM 限制），请使用 '_' 替代"
            )
        existing = await mcp_repo.find_server_by_name(session, kwargs["server_name"])
        if existing:
            raise ConflictError(f"MCP Server 名称 '{kwargs['server_name']}' 已存在")

    for key, value in kwargs.items():
        if hasattr(server, key) and value is not None:
            setattr(server, key, value)

    # 发布且不需要审批时同步到所有主 Key，否则从主 Key 中移除
    if server.is_published and not server.requires_approval:
        from services import ai_key_service

        await ai_key_service.sync_public_resource_to_all_keys(
            session, "mcps", server.id
        )
    else:
        from services import ai_key_service

        await ai_key_service.remove_public_resource_from_all_keys(
            session, "mcps", server.id
        )

    await session.flush()

    try:
        await _sync_server_to_litellm(server)
    except LiteLLMError as e:
        await session.rollback()
        logger.error("sync mcp server to litellm failed: %s", str(e))
        raise ValidationError("保存失败，服务器内部错误")

    await session.commit()
    await session.refresh(server)

    return _serialize_server(server)


async def delete_server(session: AsyncSession, server_id: int) -> None:
    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server:
        raise NotFoundError("mcp_server", server_id)

    litellm_server_id = server.server_id
    from services import ai_key_service

    await ai_key_service.remove_public_resource_from_all_keys(
        session, "mcps", server_id
    )
    await mcp_repo.delete_server(session, server_id)
    await session.commit()

    # 在 LiteLLM 侧禁用而非删除
    if litellm_server_id:
        try:
            await litellm_client.update_mcp_server(
                server_id=litellm_server_id,
                allow_all_keys=False,
            )
        except LiteLLMError:
            pass  # LiteLLM 禁用失败不影响平台删除


# ─── MCP Versions ────────────────────────────────────────────────────────────


async def list_versions(
    session: AsyncSession,
    server_id: int,
    include_deprecated: bool = True,
) -> list[dict]:
    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server:
        raise NotFoundError("mcp_server", server_id)
    versions = await mcp_version_repo.list_versions(
        session, server_id, include_deprecated
    )
    return [_serialize_version(v) for v in versions]


async def create_version(
    session: AsyncSession,
    server_id: int,
    *,
    version: str,
    url: str,
    transport: str,
    version_label: str = "",
    auth_type: str = "none",
    credentials: dict | None = None,
    mcp_info: dict | None = None,
    allowed_tools: list | None = None,
    extra_headers: list[str] | None = None,
    instructions: str = "",
    change_log: str = "",
    source: str = "manual",
    created_by: int | None = None,
) -> dict:
    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server:
        raise NotFoundError("mcp_server", server_id)
    if transport not in ("sse", "http", "streamable_http", "streamableHttp"):
        raise ValidationError("transport 只支持 sse 或 streamableHttp")
    if await mcp_version_repo.find_by_server_and_version(session, server_id, version):
        raise ConflictError(f"版本号 '{version}' 已存在")

    v = McpServerVersion(
        server_id=server_id,
        version=version,
        version_label=version_label,
        is_active=False,
        lifecycle_status="inactive",
        source=source,
        url=url,
        transport=transport,
        auth_type=auth_type,
        credentials=credentials or {},
        mcp_info=mcp_info or {},
        allowed_tools=allowed_tools or [],
        extra_headers=extra_headers or [],
        instructions=instructions,
        change_log=change_log,
        created_by=created_by,
    )
    v = await mcp_version_repo.create(session, v)
    await session.commit()
    return _serialize_version(v)


async def activate_version(
    session: AsyncSession, server_id: int, version_id: int
) -> dict:
    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server:
        raise NotFoundError("mcp_server", server_id)
    version = await mcp_version_repo.find_by_id(session, version_id)
    if not version or version.server_id != server_id:
        raise NotFoundError("mcp_server_version", version_id)

    try:
        await versioning_service.activate_version(
            session,
            version,
            server,
            version.server_id,
            mcp_version_repo,
            on_sync=_sync_version_to_litellm,
            apply_snapshot=_apply_version_snapshot_to_server,
        )
    except LiteLLMError as e:
        await session.rollback()
        logger.error("activate mcp version litellm sync failed: %s", str(e))
        raise ValidationError("激活失败：LiteLLM 同步失败，请稍后重试")

    # 激活成功后立即触发新 active 版本健康检查
    try:
        await health_check_server(session, server_id)
    except (ValidationError, LiteLLMError):
        pass

    await session.refresh(server)
    return _serialize_server(server)


async def deprecate_version(
    session: AsyncSession,
    server_id: int,
    version_id: int,
    sunset_date: datetime | None = None,
) -> dict:
    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server:
        raise NotFoundError("mcp_server", server_id)
    version = await mcp_version_repo.find_by_id(session, version_id)
    if not version or version.server_id != server_id:
        raise NotFoundError("mcp_server_version", version_id)

    await versioning_service.deprecate(session, version, mcp_version_repo, sunset_date)
    version = await mcp_version_repo.find_by_id(session, version_id)
    return _serialize_version(version)


async def _apply_version_snapshot_to_server(
    server: McpServer, version: McpServerVersion
) -> None:
    """把 active 版本的运行时快照拷贝到主表（主表 = active 版本冗余快照）。"""
    server.url = version.url
    server.transport = version.transport
    server.auth_type = version.auth_type
    server.credentials = version.credentials
    server.mcp_info = version.mcp_info
    server.allowed_tools = version.allowed_tools
    server.extra_headers = version.extra_headers
    server.instructions = version.instructions


def _serialize_version(v: McpServerVersion) -> dict:
    return {
        "id": v.id,
        "server_id": v.server_id,
        "version": v.version,
        "version_label": v.version_label,
        "is_active": v.is_active,
        "lifecycle_status": v.lifecycle_status,
        "sunset_date": v.sunset_date.isoformat() if v.sunset_date else None,
        "source": v.source,
        "url": v.url,
        "transport": v.transport,
        "auth_type": v.auth_type,
        "change_log": v.change_log,
        "auto_discovered_version": v.auto_discovered_version,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


# ─── MCP Tools ───────────────────────────────────────────────────────────────


async def refresh_tools(session: AsyncSession, server_id: int) -> list[dict]:
    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server:
        raise NotFoundError("mcp_server", server_id)

    creds = server.credentials if server.credentials else None
    litellm_transport = to_litellm_transport(server.transport)
    try:
        remote_tools = await litellm_client.list_mcp_tools_from_server(
            url=server.url,
            transport=litellm_transport,
            auth_type=server.auth_type if server.auth_type != "none" else None,
            credentials=creds,
        )
    except LiteLLMError as e:
        logger.error("failed to fetch tools from mcp server: %s", str(e))
        raise ValidationError(f"无法从 MCP Server 获取工具列表: {e}")

    # 保留已有 tool 的计费信息
    existing_tools = await mcp_repo.find_tools_by_server(session, server_id)
    billing_map = {
        t.tool_name: {
            "billing_type": t.billing_type,
            "internal_cost_per_call": t.internal_cost_per_call,
            "external_cost_per_call": t.external_cost_per_call,
        }
        for t in existing_tools
        if t.billing_type or t.internal_cost_per_call or t.external_cost_per_call
    }

    await mcp_repo.delete_tools_by_server(session, server_id)

    new_tools = []
    for tool_data in remote_tools:
        tool_name = tool_data.get("name", "")
        namespaced = f"{server.server_name}_{tool_name}"
        billing = billing_map.get(tool_name, {})
        tool = McpTool(
            server_id=server_id,
            tool_name=tool_name,
            namespaced_name=namespaced,
            display_name=tool_data.get("display_name", tool_name),
            description=tool_data.get("description", ""),
            input_schema=tool_data.get(
                "inputSchema", tool_data.get("input_schema", {})
            ),
            billing_type=billing.get("billing_type"),
            internal_cost_per_call=billing.get("internal_cost_per_call"),
            external_cost_per_call=billing.get("external_cost_per_call"),
        )
        new_tools.append(tool)

    if new_tools:
        await mcp_repo.bulk_create_tools(session, new_tools)
    await session.commit()

    return [_serialize_tool(t) for t in new_tools]


async def get_tools(session: AsyncSession, server_id: int) -> list[dict]:
    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server:
        raise NotFoundError("mcp_server", server_id)
    tools = await mcp_repo.find_tools_by_server(session, server_id)
    return [_serialize_tool(t) for t in tools]


async def update_tool_billing(
    session: AsyncSession,
    tool_id: int,
    billing_type: str | None = None,
    internal_cost_per_call: float | None = None,
    external_cost_per_call: float | None = None,
) -> dict:
    tool = await mcp_repo.find_tool_by_id(session, tool_id)
    if not tool:
        raise NotFoundError("mcp_tool", tool_id)

    if billing_type is not None:
        tool.billing_type = billing_type
    if internal_cost_per_call is not None:
        tool.internal_cost_per_call = internal_cost_per_call
    if external_cost_per_call is not None:
        tool.external_cost_per_call = external_cost_per_call

    await session.commit()
    await session.refresh(tool)

    # 重新同步 server 的 cost_info 到 LiteLLM
    server = await mcp_repo.find_server_by_id(session, tool.server_id)
    if server and server.litellm_synced:
        # 确保 tools relationship 包含最新数据
        await session.refresh(server, ["tools"])
        try:
            await _sync_server_to_litellm(server)
            await session.commit()
        except LiteLLMError as e:
            logger.error(
                "sync mcp cost to litellm failed after tool billing update: %s", str(e)
            )

    return _serialize_tool(tool)


# ─── Health Check ────────────────────────────────────────────────────────────


async def health_check_server(session: AsyncSession, server_id: int) -> dict:
    from datetime import datetime

    server = await mcp_repo.find_server_by_id(session, server_id)
    if not server:
        raise NotFoundError("mcp_server", server_id)

    litellm_transport = to_litellm_transport(server.transport)
    try:
        await litellm_client.test_mcp_connection(
            url=server.url,
            transport=litellm_transport,
            auth_type=server.auth_type if server.auth_type != "none" else None,
            credentials=server.credentials if server.credentials else None,
        )
        server.status = "healthy"
        server.health_check_error = None
    except LiteLLMError as e:
        server.status = "unhealthy"
        server.health_check_error = str(e)

    server.last_health_check = datetime.utcnow()
    await session.commit()
    await session.refresh(server)
    return _serialize_server(server)


# ─── LiteLLM Sync ───────────────────────────────────────────────────────────


async def _push_server_config_to_litellm(
    server: McpServer, snapshot: McpServer | McpServerVersion
) -> None:
    """将运行时配置同步到 LiteLLM，同步状态写主表。

    snapshot 提供随版本变化的运行时字段（url/transport/auth_type/credentials/
    mcp_info/extra_headers/instructions）；server 提供 server_name/description/工具计费
    （server 级，不随版本变）。
    """
    from datetime import datetime

    mcp_info = _build_mcp_info(server, snapshot.mcp_info)
    litellm_transport = to_litellm_transport(snapshot.transport)
    auth = snapshot.auth_type if snapshot.auth_type != "none" else None
    creds = snapshot.credentials if snapshot.credentials else None
    headers = snapshot.extra_headers if snapshot.extra_headers else None

    if server.litellm_synced:
        await litellm_client.update_mcp_server(
            server_id=server.server_id,
            server_name=server.server_name,
            url=snapshot.url,
            transport=litellm_transport,
            auth_type=auth,
            credentials=creds,
            description=server.description,
            instructions=snapshot.instructions,
            mcp_info=mcp_info,
            extra_headers=headers,
            allow_all_keys=True,
        )
    else:
        await litellm_client.create_mcp_server(
            server_id=server.server_id,
            server_name=server.server_name,
            url=snapshot.url,
            transport=litellm_transport,
            auth_type=auth,
            credentials=creds,
            description=server.description,
            instructions=snapshot.instructions,
            mcp_info=mcp_info,
            extra_headers=headers,
        )
    server.litellm_synced = True
    server.litellm_sync_error = None
    server.litellm_synced_at = datetime.utcnow()


async def _sync_server_to_litellm(server: McpServer) -> None:
    await _push_server_config_to_litellm(server, server)


async def _sync_version_to_litellm(
    server: McpServer, version: McpServerVersion
) -> None:
    """用 active 版本的运行时快照覆盖同步 LiteLLM（server_name 跨版本不变）。"""
    await _push_server_config_to_litellm(server, version)


def _build_mcp_info(
    server: McpServer, base_mcp_info: dict | None = None
) -> dict | None:
    """组装 mcp_info，包含 LiteLLM 需要的 mcp_server_cost_info。

    base_mcp_info 默认取 server.mcp_info；版本同步时传入版本的 mcp_info 作为基底，
    成本信息始终按 server 级工具计费实时计算。
    """
    from core.config import settings

    base = base_mcp_info if base_mcp_info is not None else server.mcp_info
    mcp_info = dict(base) if base else {}
    rate = settings.usd_to_cny_rate

    # 构建成本信息（平台存人民币，LiteLLM 需要美元）
    tool_costs = {}
    if server.tools:
        for tool in server.tools:
            if tool.external_cost_per_call:
                tool_costs[tool.tool_name] = round(
                    float(tool.external_cost_per_call) / rate, 6
                )

    default_cost = (
        round(float(server.external_cost_per_call) / rate, 6)
        if server.external_cost_per_call
        else None
    )

    if default_cost or tool_costs:
        cost_info: dict = {}
        if default_cost:
            cost_info["default_cost_per_query"] = default_cost
        if tool_costs:
            cost_info["tool_name_to_cost_per_query"] = tool_costs
        mcp_info["mcp_server_cost_info"] = cost_info
    else:
        mcp_info["mcp_server_cost_info"] = None

    # 保留 description 和 server_name 供 LiteLLM 展示
    mcp_info["description"] = server.description or ""
    mcp_info["server_name"] = server.server_name

    return mcp_info if mcp_info else None


# ─── Serializers ─────────────────────────────────────────────────────────────


def _serialize_server(server: McpServer) -> dict:
    active = next((v for v in (server.versions or []) if v.is_active), None)
    return {
        "id": server.id,
        "server_id": server.server_id,
        "name": server.name,
        "server_name": server.server_name,
        "description": server.description,
        "url": server.url,
        "transport": server.transport,
        "auth_type": server.auth_type,
        "credentials": server.credentials,
        "instructions": server.instructions,
        "mcp_info": server.mcp_info,
        "extra_headers": server.extra_headers,
        "allowed_tools": server.allowed_tools,
        "authorization_url": server.authorization_url,
        "token_url": server.token_url,
        "registration_url": server.registration_url,
        "category": server.category,
        "tags": server.tags,
        "author": server.author,
        "icon_url": server.icon_url,
        "documentation_url": server.documentation_url,
        "source_url": server.source_url,
        "billing_type": server.billing_type,
        "internal_cost_per_call": float(server.internal_cost_per_call),
        "external_cost_per_call": float(server.external_cost_per_call),
        "is_active": server.is_active,
        "is_published": server.is_published,
        "visibility_type": server.visibility_type,
        "requires_approval": server.requires_approval,
        "status": server.status,
        "call_count": server.call_count or 0,
        "last_health_check": (
            server.last_health_check.isoformat() if server.last_health_check else None
        ),
        "health_check_error": server.health_check_error,
        "litellm_synced": server.litellm_synced,
        "litellm_sync_error": server.litellm_sync_error,
        "current_version_id": server.current_version_id,
        "active_version": _serialize_version(active) if active else None,
        "created_by": server.created_by,
        "created_at": server.created_at.isoformat() if server.created_at else None,
        "updated_at": server.updated_at.isoformat() if server.updated_at else None,
    }


def _serialize_tool(tool: McpTool) -> dict:
    return {
        "id": tool.id,
        "server_id": tool.server_id,
        "tool_name": tool.tool_name,
        "namespaced_name": tool.namespaced_name,
        "display_name": tool.display_name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "billing_type": tool.billing_type,
        "internal_cost_per_call": (
            float(tool.internal_cost_per_call)
            if tool.internal_cost_per_call is not None
            else None
        ),
        "external_cost_per_call": (
            float(tool.external_cost_per_call)
            if tool.external_cost_per_call is not None
            else None
        ),
        "is_active": tool.is_active,
    }


# ─── Categories ─────────────────────────────────────────────────────────────


async def list_categories(session: AsyncSession) -> list[dict]:
    cats = await mcp_repo.list_categories(session)
    return [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "sort_order": c.sort_order,
        }
        for c in cats
    ]


async def create_category(
    session: AsyncSession, name: str, description: str = "", sort_order: int = 0
) -> dict:
    from models.db import McpCategory

    existing = await mcp_repo.find_category_by_name(session, name)
    if existing:
        raise ConflictError(f"分类 '{name}' 已存在")

    cat = McpCategory(name=name, description=description, sort_order=sort_order)
    cat = await mcp_repo.create_category(session, cat)
    await session.commit()
    return {
        "id": cat.id,
        "name": cat.name,
        "description": cat.description,
        "sort_order": cat.sort_order,
    }


async def delete_category(session: AsyncSession, category_id: int) -> None:
    cat = await mcp_repo.find_category_by_id(session, category_id)
    if not cat:
        raise NotFoundError("mcp_category", category_id)
    await mcp_repo.delete_category(session, category_id)
    await session.commit()
