"""S7 阶段一 · CLI 分发通道测试（依赖 dev 中间件真实 DB）。

- CLI scoped token 生成/哈希/serialize 隔离；scope 校验；CRUD。
- require_cli_scope 分权（403 / 命中 / 通配）。
- cli_search 搜索：published-only、hidden 排除、label 过滤、sort。
- 权限点 cli_token:* 已注册。
"""

import io
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from core.database import get_worker_session_factory
from core.deps import require_cli_scope
from exceptions import NotFoundError, ValidationError
from models.db import AiKey, Permission, Skill, SkillVersion
from repositories import ai_key_repo, skill_label_repo, skill_repo
from services import cli_token_service, skill_service


def _session():
    return get_worker_session_factory()()


def _valid_zip(name: str = "cli-skill") -> bytes:
    skill_md = (
        f"---\nname: {name}\ndescription: A cli test skill.\n---\n\n# {name}\n\nBody."
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", skill_md)
    return buf.getvalue()


async def _make_published_skill(suffix: str | None = None) -> tuple[int, str]:
    name = f"test_cli_{(suffix or uuid.uuid4().hex)[:8]}"
    session = _session()
    try:
        data = await skill_service.create_skill(
            session,
            name=name,
            version="1.0.0",
            zip_content=_valid_zip(name),
            zip_filename=f"{name}.zip",
        )
    finally:
        await session.close()
    sid = int(data["id"])
    async with _session() as s:
        skill = await skill_repo.find_by_id(s, sid)
        assert skill is not None
        skill.is_published = True
        skill.hidden = False
        await s.commit()
        await s.refresh(skill)
        uuid_id = skill.skill_id
    return sid, uuid_id


async def _cleanup_tokens(token_ids: list[int]) -> None:
    if not token_ids:
        return
    async with _session() as s:
        await s.execute(delete(AiKey).where(AiKey.id.in_(token_ids)))
        await s.commit()


async def _cleanup_skills(skill_ids: list[int]) -> None:
    if not skill_ids:
        return
    async with _session() as s:
        await s.execute(
            delete(SkillVersion).where(SkillVersion.skill_id.in_(skill_ids))
        )
        await s.execute(delete(Skill).where(Skill.id.in_(skill_ids)))
        await s.commit()


# ─── CLI scoped token ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cli_token_create_returns_plaintext_once_and_stores_hash():
    created_ids: list[int] = []
    try:
        session = _session()
        try:
            data, raw = await cli_token_service.create_token(
                session,
                name="test_cli_token_create",
                description="d",
                scopes=["skill:search", "skill:install"],
                owner_id=990001,
            )
        finally:
            await session.close()
        created_ids.append(data["id"])

        assert raw.startswith("sk_cli_")
        assert data["key_value"] == raw
        assert data["token_prefix"].startswith("sk_cli_")
        assert set(data["scopes"]) == {"skill:search", "skill:install"}
        assert data["is_active"] is True

        # 入库哈希正确，且仅存哈希（litellm_key_id 为 NULL）
        async with _session() as s:
            stored = await ai_key_repo.find_by_id(s, data["id"])
            assert stored is not None
            assert stored.token_kind == "cli"
            assert stored.token_hash == cli_token_service.hash_cli_token(raw)
            assert stored.litellm_key_id is None
            # 明文 token 不入库
            assert raw not in (stored.token_hash or "")
    finally:
        await _cleanup_tokens(created_ids)


@pytest.mark.asyncio
async def test_cli_token_find_by_hash_resolves_and_isolates():
    created_ids: list[int] = []
    try:
        session = _session()
        try:
            data, raw = await cli_token_service.create_token(
                session,
                name="test_cli_token_hash",
                description="",
                scopes=["skill:read"],
                owner_id=990002,
            )
        finally:
            await session.close()
        created_ids.append(data["id"])

        async with _session() as s:
            found = await ai_key_repo.find_cli_by_hash(
                s, cli_token_service.hash_cli_token(raw)
            )
            assert found is not None
            assert found.id == data["id"]
            # 错误哈希 / 伪造 token 哈希 → None
            assert await ai_key_repo.find_cli_by_hash(s, "deadbeef") is None
            fake = cli_token_service.hash_cli_token("sk_cli_notarealtoken")
            assert await ai_key_repo.find_cli_by_hash(s, fake) is None
    finally:
        await _cleanup_tokens(created_ids)


@pytest.mark.asyncio
async def test_cli_token_invalid_scope_rejected():
    created_ids: list[int] = []
    try:
        session = _session()
        try:
            with pytest.raises(ValidationError):
                await cli_token_service.create_token(
                    session,
                    name="test_cli_bad_scope",
                    description="",
                    scopes=["skill:admin"],  # 不支持的 scope
                    owner_id=990003,
                )
        finally:
            await session.close()
    finally:
        await _cleanup_tokens(created_ids)


@pytest.mark.asyncio
async def test_cli_token_crud_and_revoke():
    created_ids: list[int] = []
    try:
        session = _session()
        try:
            data, _raw = await cli_token_service.create_token(
                session,
                name="test_cli_crud",
                description="",
                scopes=["skill:read"],
                owner_id=990004,
            )
        finally:
            await session.close()
        tid = data["id"]
        created_ids.append(tid)

        # list
        async with _session() as s:
            page = await cli_token_service.list_tokens(s, owner_id=990004)
        assert page["total"] >= 1
        assert any(t["id"] == tid for t in page["items"])

        # update scopes
        session = _session()
        try:
            updated = await cli_token_service.update_token(
                session, tid, scopes=["skill:install"], name="renamed"
            )
        finally:
            await session.close()
        assert updated["scopes"] == ["skill:install"]
        assert updated["name"] == "renamed"

        # revoke
        session = _session()
        try:
            await cli_token_service.revoke_token(session, tid)
        finally:
            await session.close()
        async with _session() as s:
            after = await cli_token_service.get_token(s, tid)
        assert after["is_active"] is False

        # get 不存在的 cli token（或 llm 行）→ NotFoundError
        session = _session()
        try:
            with pytest.raises(NotFoundError):
                await cli_token_service.get_token(session, 0)
        finally:
            await session.close()
    finally:
        await _cleanup_tokens(created_ids)


@pytest.mark.asyncio
async def test_cli_token_permissions_registered():
    async with _session() as s:
        for code in (
            "cli_token:create",
            "cli_token:read",
            "cli_token:update",
            "cli_token:delete",
        ):
            result = await s.execute(select(Permission).where(Permission.code == code))
            perm = result.scalar_one_or_none()
            assert perm is not None
            assert perm.resource == "cli_token"


# ─── require_cli_scope 分权 ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_cli_scope_enforces():
    checker_install = require_cli_scope("skill:install")

    # scope 不足 → 403
    with pytest.raises(HTTPException) as exc:
        await checker_install({"scopes": ["skill:read"]})
    assert exc.value.status_code == 403

    # 命中 → 放行
    identity = await checker_install({"scopes": ["skill:install"]})
    assert identity["scopes"] == ["skill:install"]

    # 通配 skill:* → 放行
    identity_wild = await checker_install({"scopes": ["skill:*"]})
    assert identity_wild is not None


# ─── CLI 搜索（cli_search_skills）────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cli_search_published_only_and_hidden_excluded():
    pub_id, _ = await _make_published_skill("pub")
    unpub_id, _ = await _make_published_skill("unpub")
    try:
        async with _session() as s:
            skill = await skill_repo.find_by_id(s, unpub_id)
            assert skill is not None
            skill.is_published = False
            await s.commit()

        async with _session() as s:
            items = await skill_repo.cli_search_skills(s, q=None)
            ids = {it.id for it in items}
            assert pub_id in ids
            assert unpub_id not in ids  # 未发布排除

            # hidden 排除
            skill_pub = await skill_repo.find_by_id(s, pub_id)
            skill_pub.hidden = True
            await s.commit()
            items2 = await skill_repo.cli_search_skills(s, q=None)
            assert pub_id not in {it.id for it in items2}
            skill_pub.hidden = False
            await s.commit()
    finally:
        await _cleanup_skills([pub_id, unpub_id])


@pytest.mark.asyncio
async def test_cli_search_label_filter_and_sort():
    sid_a, _ = await _make_published_skill("a")
    sid_b, _ = await _make_published_skill("b")
    try:
        async with _session() as s:
            await skill_label_repo.grant(
                s, sid_a, await _label_def_id(s, "recommended"), None, ""
            )
            await s.commit()

        async with _session() as s:
            # label 过滤：仅返回带 recommended 的
            ids_with = await skill_label_repo.find_skill_ids_by_label_name(
                s, "recommended"
            )
            assert sid_a in ids_with
            items = await skill_repo.cli_search_skills(s, label_skill_ids=ids_with)
            assert sid_a in {it.id for it in items}
            assert sid_b not in {it.id for it in items}

            # sort=name 不报错且返回结果
            by_name = await skill_repo.cli_search_skills(s, sort="name")
            assert len(by_name) >= 1
    finally:
        await _cleanup_skills([sid_a, sid_b])


async def _label_def_id(s, name: str) -> int:
    definition = await skill_label_repo.find_definition_by_name(s, name)
    assert definition is not None, "recommended 标签定义未 seed"
    return definition.id
