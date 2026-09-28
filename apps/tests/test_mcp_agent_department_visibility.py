"""MCP / 智能体部门可见测试（走真实 DB，依赖 dev 中间件运行）。

覆盖（087 migration 后）：
- Agent：create/update 部门可见 + 主 Key 仅同步部门成员；列表按 viewer 部门过滤
- MCP：update 部门可见字段设置/清空 + 校验；主 Key 部门分支
- 写入收敛：skill/mcp/agent 拒绝 private/unlisted/selected
"""

import uuid

import pytest
from sqlalchemy import delete, select

from core.database import get_worker_session_factory
from exceptions import ValidationError
from models.db import (
    Agent,
    AiKey,
    Department,
    McpServer,
    McpServerVersion,
    McpTool,
    User,
    UserDepartment,
)
from services import agent_service, mcp_service, skill_service
from services import visibility_service


def _session():
    return get_worker_session_factory()()


async def _make_user(suffix: str = "") -> User:
    uname = f"deptvis_{suffix}{uuid.uuid4().hex[:8]}"
    session = _session()
    try:
        user = User(
            username=uname,
            email=f"{uname}@test.local",
            hashed_password="x",
            is_admin=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
    finally:
        await session.close()


async def _make_department(name: str) -> Department:
    session = _session()
    try:
        dept = Department(name=name, is_active=True)
        session.add(dept)
        await session.commit()
        await session.refresh(dept)
        return dept
    finally:
        await session.close()


async def _make_personal_main_key(owner_id: int) -> int:
    session = _session()
    try:
        key = AiKey(
            name=f"deptvis-key-{owner_id}",
            owner_type="user",
            owner_id=owner_id,
            key_type="personal_main",
            models=[],
            skills=[],
            mcps=[],
            agents=[],
            is_active=True,
        )
        session.add(key)
        await session.commit()
        await session.refresh(key)
        return key.id
    finally:
        await session.close()


async def _add_membership(user_id: int, dept_id: int) -> None:
    session = _session()
    try:
        session.add(UserDepartment(user_id=user_id, department_id=dept_id))
        await session.commit()
    finally:
        await session.close()


async def _key_resource_ids(key_id: int, field: str) -> list:
    async with _session() as s:
        key = await s.get(AiKey, key_id)
        return list(getattr(key, field) or [])


async def _cleanup(state: dict) -> None:
    async with _session() as s:
        if "agent_ids" in state:
            await s.execute(delete(Agent).where(Agent.id.in_(state["agent_ids"])))
        if "mcp_ids" in state:
            await s.execute(
                delete(McpTool).where(McpTool.server_id.in_(state["mcp_ids"]))
            )
            await s.execute(
                delete(McpServerVersion).where(
                    McpServerVersion.server_id.in_(state["mcp_ids"])
                )
            )
            await s.execute(delete(McpServer).where(McpServer.id.in_(state["mcp_ids"])))
        await s.execute(delete(AiKey).where(AiKey.id.in_(state["key_ids"])))
        await s.execute(
            delete(UserDepartment).where(UserDepartment.user_id.in_(state["user_ids"]))
        )
        await s.execute(delete(User).where(User.id.in_(state["user_ids"])))
        if state.get("dept_ids"):
            await s.execute(
                delete(Department).where(Department.id.in_(state["dept_ids"]))
            )
        await s.commit()


async def _make_mcp(suffix: str) -> int:
    session = _session()
    try:
        data = await mcp_service.create_server(
            session,
            name=f"deptvis-mcp-{suffix}",
            server_name=f"deptvis_mcp_{suffix}{uuid.uuid4().hex[:6]}",
            url="https://example.com/mcp",
            transport="sse",
        )
    finally:
        await session.close()
    return int(data["id"])


# ─── Agent ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_department_visibility_syncs_member_keys_and_filters_list():
    member = await _make_user("m")
    outsider = await _make_user("o")
    dept = await _make_department("部门可见测试组")
    state = {
        "user_ids": [member.id, outsider.id],
        "dept_ids": [dept.id],
        "key_ids": [],
        "agent_ids": [],
    }
    try:
        await _add_membership(member.id, dept.id)
        member_key = await _make_personal_main_key(member.id)
        outsider_key = await _make_personal_main_key(outsider.id)
        state["key_ids"] += [member_key, outsider_key]

        session = _session()
        try:
            data = await agent_service.create_agent(
                session,
                name=f"部门智能体{uuid.uuid4().hex[:6]}",
                platform="coze",
                is_published=True,
                visibility_type="department",
                visible_department_id=dept.id,
            )
        finally:
            await session.close()
        agent_id = int(data["id"])
        state["agent_ids"].append(agent_id)

        # 主 Key：仅部门成员拿到，非成员不拿
        assert agent_id in await _key_resource_ids(member_key, "agents")
        assert agent_id not in await _key_resource_ids(outsider_key, "agents")

        # 列表过滤：成员可见 / 非成员不可见 / admin 全见
        session = _session()
        try:
            member_view = await agent_service.list_agents(
                session,
                viewer_id=member.id,
                is_admin=False,
                viewer_department_ids=[dept.id],
            )
            outsider_view = await agent_service.list_agents(
                session,
                viewer_id=outsider.id,
                is_admin=False,
                viewer_department_ids=[],
            )
            admin_view = await agent_service.list_agents(
                session,
                viewer_id=1,
                is_admin=True,
            )
        finally:
            await session.close()
        assert agent_id in {a["id"] for a in member_view["items"]}
        assert agent_id not in {a["id"] for a in outsider_view["items"]}
        assert agent_id in {a["id"] for a in admin_view["items"]}

        # 切回公开：广播全体主 Key
        session = _session()
        try:
            await agent_service.update_agent(
                session, agent_id, visibility_type="all", visible_department_id=0
            )
        finally:
            await session.close()
        assert agent_id in await _key_resource_ids(outsider_key, "agents")
    finally:
        await _cleanup(state)


@pytest.mark.asyncio
async def test_agent_rejects_department_without_dept_and_legacy_values():
    dept = await _make_department("部门可见测试组2")
    state = {"user_ids": [], "dept_ids": [dept.id], "key_ids": []}
    try:
        session = _session()
        try:
            with pytest.raises(ValidationError):
                await agent_service.create_agent(
                    session,
                    name=f"无部门智能体{uuid.uuid4().hex[:6]}",
                    platform="coze",
                    is_published=True,
                    visibility_type="department",
                )
        finally:
            await session.close()

        session = _session()
        try:
            with pytest.raises(ValidationError):
                await agent_service.create_agent(
                    session,
                    name=f"私有智能体{uuid.uuid4().hex[:6]}",
                    platform="coze",
                    visibility_type="private",
                )
        finally:
            await session.close()
    finally:
        await _cleanup(state)


# ─── MCP ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_update_sets_department_visibility_and_syncs_member_keys(
    monkeypatch,
):
    # 隔离 LiteLLM（dev 环境 MCP 注册偶发 502，与可见性逻辑无关）
    async def _no_litellm_sync(*args, **kwargs):
        return None

    monkeypatch.setattr(mcp_service, "_sync_server_to_litellm", _no_litellm_sync)

    member = await _make_user("mm")
    dept = await _make_department("MCP部门可见测试组")
    state = {
        "user_ids": [member.id],
        "dept_ids": [dept.id],
        "key_ids": [],
        "mcp_ids": [],
    }
    try:
        await _add_membership(member.id, dept.id)
        member_key = await _make_personal_main_key(member.id)
        state["key_ids"].append(member_key)

        server_id = await _make_mcp("d")
        state["mcp_ids"].append(server_id)

        session = _session()
        try:
            data = await mcp_service.update_server(
                session,
                server_id,
                actor_id=1,
                actor_is_admin=True,
                is_published=True,
                requires_approval=False,
                visibility_type="department",
                visible_department_id=dept.id,
            )
        finally:
            await session.close()
        assert data["visible_department_id"] == dept.id
        assert server_id in await _key_resource_ids(member_key, "mcps")

        # 清空：切回 all 并清部门归属
        session = _session()
        try:
            data = await mcp_service.update_server(
                session,
                server_id,
                actor_id=1,
                actor_is_admin=True,
                visibility_type="all",
                visible_department_id=0,
            )
        finally:
            await session.close()
        assert data["visible_department_id"] is None

        # department 但缺部门 → 400
        session = _session()
        try:
            with pytest.raises(ValidationError):
                await mcp_service.update_server(
                    session,
                    server_id,
                    actor_id=1,
                    visibility_type="department",
                    visible_department_id=0,
                )
        finally:
            await session.close()

        # 写入收敛：unlisted 拒绝
        session = _session()
        try:
            with pytest.raises(ValidationError):
                await mcp_service.update_server(
                    session, server_id, actor_id=1, visibility_type="unlisted"
                )
        finally:
            await session.close()
    finally:
        await _cleanup(state)


# ─── 写入收敛（visibility_service）────────────────────────────────────────────


def test_write_visibility_rejects_legacy_values():
    for legacy in ("private", "unlisted", "selected"):
        with pytest.raises(ValidationError):
            visibility_service.validate_write_visibility(legacy)
    visibility_service.validate_write_visibility("all")
    visibility_service.validate_write_visibility("department")


@pytest.mark.asyncio
async def test_skill_create_rejects_private_visibility():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: deptvis-skill\ndescription: t\n---\n# t\n\nbody\n",
        )
    session = _session()
    try:
        with pytest.raises(ValidationError):
            await skill_service.create_skill(
                session,
                name=f"deptvis-skill-{uuid.uuid4().hex[:6]}",
                version="1.0.0",
                zip_content=buf.getvalue(),
                zip_filename="s.zip",
                visibility_type="private",
            )
    finally:
        await session.close()
