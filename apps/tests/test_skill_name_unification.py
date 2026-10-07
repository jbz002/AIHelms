"""单名称契约测试（2026-10 / 090 迁移配套）。

覆盖：name ≡ SKILL.md frontmatter name，全局唯一，双向绑定。
- 创建：name 以包内 frontmatter 为准（form name 可选，不一致 400；缺失/非 kebab 400）
- 改名（DB→markdown）：重写 zip 内 SKILL.md + 顶层目录 + 重算 hash + 同步版本行
- 激活（markdown→DB）：版本 frontmatter name 回写主表；撞他人现名 409
"""

import io
import os
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from starlette.datastructures import UploadFile

from api.v1 import contributor_skills as cs
from core.database import get_worker_session_factory
from exceptions import ConflictError, ValidationError
from models.db import Skill, SkillVersion, User
from services import skill_service


def _session():
    return get_worker_session_factory()()


async def _owner_id() -> int:
    async with _session() as s:
        result = await s.execute(select(User.id).limit(1))
        row = result.scalars().first()
        assert row is not None, "测试需至少一个真实用户"
        return int(row)


def _zip_bytes(fm_name: str, *, dir_name: str | None = None) -> bytes:
    """构造 zip：顶层目录 dir_name（默认 = fm_name，测 dir_mismatch 时可错开）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{dir_name or fm_name}/SKILL.md",
            f"---\nname: {fm_name}\ndescription: test skill\n---\n# {fm_name}\n\ntest body\n",
        )
    return buf.getvalue()


def _upload_file(data: bytes, filename: str = "skill.zip") -> UploadFile:
    buf = io.BytesIO(data)
    return UploadFile(file=buf, filename=filename)


async def _create(owner: int, name: str = "", *, fm_name: str | None = None) -> dict:
    """走贡献 router 创建（name 可传空测「不传 name」语义）。"""
    fm = fm_name or f"sn{uuid.uuid4().hex[:10]}"
    session = _session()
    try:
        data = await cs.create_my_skill(
            name=name,
            icon="📦",
            icon_url=None,
            description="",
            category="通用",
            version="1.0.0",
            tags="[]",
            author="tester",
            agent_install_prompt="",
            usage_instructions="",
            visibility_type="all",
            source_url="",
            zip_file=_upload_file(_zip_bytes(fm)),
            session=session,
            current_user={
                "id": owner,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
    finally:
        await session.close()
    return data["data"]


async def _cleanup(skill_id: int) -> None:
    async with _session() as s:
        paths = []
        skill = await s.get(Skill, skill_id)
        if skill:
            paths.append(skill.zip_path)
            for v in skill.versions or []:
                paths.append(v.zip_path)
        await s.execute(delete(SkillVersion).where(SkillVersion.skill_id == skill_id))
        await s.execute(delete(Skill).where(Skill.id == skill_id))
        await s.commit()
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


# ─── 创建路径 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_name_omitted_derives_from_frontmatter():
    owner = await _owner_id()
    fm = f"sn{uuid.uuid4().hex[:10]}"
    created = await _create(owner, name="", fm_name=fm)
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.name == fm
            assert (skill.frontmatter or {}).get("name") == fm
    finally:
        await _cleanup(skill_id)


@pytest.mark.asyncio
async def test_create_name_matching_frontmatter_ok():
    owner = await _owner_id()
    fm = f"sn{uuid.uuid4().hex[:10]}"
    created = await _create(owner, name=fm, fm_name=fm)
    await _cleanup(int(created["id"]))


@pytest.mark.asyncio
async def test_create_name_mismatch_400():
    owner = await _owner_id()
    fm = f"sn{uuid.uuid4().hex[:10]}"
    session = _session()
    with pytest.raises(HTTPException) as exc:
        await cs.create_my_skill(
            name="totally-different",
            icon="📦",
            icon_url=None,
            description="",
            category="通用",
            version="1.0.0",
            tags="[]",
            author="tester",
            agent_install_prompt="",
            usage_instructions="",
            visibility_type="all",
            source_url="",
            zip_file=_upload_file(_zip_bytes(fm)),
            session=session,
            current_user={
                "id": owner,
                "is_admin": False,
                "permissions": ["skill:contribute"],
            },
        )
    await session.close()
    assert exc.value.status_code == 400
    assert "不一致" in str(exc.value.detail)
    async with _session() as s:
        result = await s.execute(
            select(Skill.id).where(Skill.name == "totally-different")
        )
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_create_duplicate_frontmatter_name_409():
    owner = await _owner_id()
    fm = f"dup{uuid.uuid4().hex[:10]}"
    first = await _create(owner, name="", fm_name=fm)
    try:
        with pytest.raises(ConflictError):
            await skill_service.create_skill(
                _session(),
                name="",
                zip_content=_zip_bytes(fm),
                zip_filename="skill.zip",
                is_published=False,
                created_by=owner,
            )
    finally:
        await _cleanup(int(first["id"]))


@pytest.mark.asyncio
async def test_create_chinese_or_missing_name_400():
    """无 frontmatter（H1 中文回填）与非 kebab frontmatter 均创建 400（admin 路径
    无贡献预检，require_valid_frontmatter_name 兜底）。"""
    owner = await _owner_id()
    # H1 中文回填
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("no-fm/SKILL.md", "# 中文标题\n\n正文段落\n")
    with pytest.raises(ValidationError):
        await skill_service.create_skill(
            _session(), name="", zip_content=buf.getvalue(), created_by=owner
        )
    # frontmatter 显式中文
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("cn/SKILL.md", "---\nname: 中文名\ndescription: t\n---\n# t\n")
    with pytest.raises(ValidationError):
        await skill_service.create_skill(
            _session(), name="", zip_content=buf2.getvalue(), created_by=owner
        )


@pytest.mark.asyncio
async def test_cli_create_name_optional():
    """CLI 通道同语义：不传 name（空串）→ DB name = frontmatter name。"""
    from api.v1 import cli as cli_api

    owner = await _owner_id()
    fm = f"cli{uuid.uuid4().hex[:10]}"
    session = _session()
    try:
        data = await cli_api.cli_create_skill(
            name="",
            description="",
            category="通用",
            version="1.0.0",
            author="",
            usage_instructions="",
            visibility_type="all",
            source_url="",
            zip_file=_upload_file(_zip_bytes(fm)),
            session=session,
            identity={"owner_type": "user", "owner_id": owner, "ai_key_id": None},
        )
    finally:
        await session.close()
    skill_id = int(data["data"]["id"])
    try:
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.name == fm
    finally:
        await _cleanup(skill_id)


# ─── 改名（DB → markdown） ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_rewrites_zip_and_syncs_versions():
    owner = await _owner_id()
    fm = f"rn{uuid.uuid4().hex[:10]}"
    created = await _create(owner, name="", fm_name=fm)
    skill_id = int(created["id"])
    new_name = f"{fm}-renamed"
    try:
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            zip_path = skill.zip_path
            with open(zip_path, "rb") as f:
                before_bytes = f.read()
            v1_before = await s.get(SkillVersion, skill.current_version_id)
            hash_before = v1_before.composite_hash

        await skill_service.update_skill(
            _session(), skill_id, actor_id=owner, actor_is_admin=True, name=new_name
        )

        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.name == new_name
            assert (skill.frontmatter or {}).get("name") == new_name
            with open(skill.zip_path, "rb") as f:
                after_bytes = f.read()
            assert after_bytes != before_bytes, "zip 未重写"
            with zipfile.ZipFile(io.BytesIO(after_bytes)) as zf:
                names = zf.namelist()
                assert f"{new_name}/SKILL.md" in names, f"顶层目录未改名: {names}"
                md = zf.read(f"{new_name}/SKILL.md").decode("utf-8")
            assert f"name: {new_name}" in md
            v1 = await s.get(SkillVersion, skill.current_version_id)
            assert v1.composite_hash != hash_before, "composite_hash 未重算"
            assert (v1.frontmatter or {}).get("name") == new_name
            assert v1.protocol_valid is True
    finally:
        await _cleanup(skill_id)


@pytest.mark.asyncio
async def test_rename_same_name_noop_keeps_zip():
    owner = await _owner_id()
    fm = f"no{uuid.uuid4().hex[:10]}"
    created = await _create(owner, name="", fm_name=fm)
    skill_id = int(created["id"])
    try:
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            with open(skill.zip_path, "rb") as f:
                before = f.read()
        await skill_service.update_skill(
            _session(), skill_id, actor_id=owner, actor_is_admin=True, name=fm
        )
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            with open(skill.zip_path, "rb") as f:
                after = f.read()
            assert after == before, "同名改名不应重写 zip"
    finally:
        await _cleanup(skill_id)


@pytest.mark.asyncio
async def test_rename_conflict_nonkebab_missing_zip():
    owner = await _owner_id()
    fm_a = f"ca{uuid.uuid4().hex[:10]}"
    fm_b = f"cb{uuid.uuid4().hex[:10]}"
    a = await _create(owner, name="", fm_name=fm_a)
    b = await _create(owner, name="", fm_name=fm_b)
    try:
        # 撞他人现名
        with pytest.raises(ConflictError):
            await skill_service.update_skill(
                _session(), int(a["id"]), actor_id=owner, name=fm_b
            )
        # 非 kebab
        with pytest.raises(ValidationError):
            await skill_service.update_skill(
                _session(), int(a["id"]), actor_id=owner, name="BadName"
            )
        # 存量包缺失
        async with _session() as s:
            skill = await s.get(Skill, int(a["id"]))
            zip_path = skill.zip_path
            skill.zip_path = ""
            await s.commit()
        os.path.exists(zip_path) and os.remove(zip_path)
        with pytest.raises(ValidationError):
            await skill_service.update_skill(
                _session(), int(a["id"]), actor_id=owner, name=f"{fm_a}-x"
            )
    finally:
        await _cleanup(int(a["id"]))
        await _cleanup(int(b["id"]))


# ─── zip 重写纯函数（DB→markdown 方向的构件） ───────────────────────────────


def test_replace_frontmatter_name_variants():
    from services.skill_content_service import replace_frontmatter_name

    # 常规：有 name 行 → 行级替换
    raw = "---\nname: old-name\ndescription: t\n---\n# body\n"
    out = replace_frontmatter_name(raw, "new-name")
    assert "name: new-name" in out and "old-name" not in out
    assert "description: t" in out and "# body" in out

    # 有 frontmatter 块但无 name 键 → 开块后插一行
    raw2 = "---\ndescription: t\n---\n# body\n"
    out2 = replace_frontmatter_name(raw2, "new-name")
    assert out2.startswith("---\nname: new-name\ndescription: t\n---\n")

    # 无 frontmatter 块 → 头部构造
    raw3 = "# body only\n"
    out3 = replace_frontmatter_name(raw3, "new-name")
    assert out3 == "---\nname: new-name\n---\n# body only\n"

    # 缩进的嵌套 name 键不受影响，仅顶层 name 被替换
    raw4 = "---\nname: old-name\nmeta:\n  name: nested\n---\n"
    out4 = replace_frontmatter_name(raw4, "new-name")
    assert "name: new-name" in out4
    assert "  name: nested" in out4


def test_rewrite_zip_skill_name_full_flow():
    from services.skill_content_service import (
        parse_skill_zip,
        rewrite_zip_skill_name,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "old-dir/SKILL.md", "---\nname: old-name\ndescription: t\n---\nbody\n"
        )
        zf.writestr("old-dir/references/guide.md", "guide")
    result = rewrite_zip_skill_name(buf.getvalue(), "new-name")
    assert result is not None and result.root_dir_renamed is True
    parsed = parse_skill_zip(result.new_bytes)
    assert parsed.frontmatter.get("name") == "new-name"
    assert "new-name/SKILL.md" in parsed.file_hashes
    assert "new-name/references/guide.md" in parsed.file_hashes
    assert "old-dir/SKILL.md" not in parsed.file_hashes

    # 无 SKILL.md → None
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as zf:
        zf.writestr("x/readme.txt", "x")
    assert rewrite_zip_skill_name(buf2.getvalue(), "new-name") is None


# ─── 激活（markdown → DB） ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_version_renames_skill_and_collision_409():
    owner = await _owner_id()
    fm_a = f"ac{uuid.uuid4().hex[:10]}"
    fm_b = f"ad{uuid.uuid4().hex[:10]}"
    fm_c = f"ae{uuid.uuid4().hex[:10]}"
    a = await _create(owner, name="", fm_name=fm_a)  # v1 fm name = fm_a
    b = await _create(owner, name="", fm_name=fm_b)  # 占名者
    try:
        skill_a_id = int(a["id"])
        # 新版本 fm name = fm_b（他人现名）→ 激活 409
        v2 = await skill_service.create_version(
            _session(),
            skill_a_id,
            version="9.9.9",
            zip_content=_zip_bytes(fm_b),
            zip_filename="v2.zip",
            created_by=owner,
        )
        with pytest.raises(ConflictError):
            await skill_service.activate_version(_session(), skill_a_id, int(v2["id"]))

        # 新版本 fm name = fm_c（无冲突）→ 激活后主表 name 回写
        v3 = await skill_service.create_version(
            _session(),
            skill_a_id,
            version="9.9.10",
            zip_content=_zip_bytes(fm_c),
            zip_filename="v3.zip",
            created_by=owner,
        )
        await skill_service.activate_version(_session(), skill_a_id, int(v3["id"]))
        async with _session() as s:
            skill = await s.get(Skill, skill_a_id)
            assert skill.name == fm_c

        # 回切 v1（fm name = fm_a）→ 主表 name 回切
        await skill_service.activate_version(
            _session(), skill_a_id, int(a["current_version_id"])
        )
        async with _session() as s:
            skill = await s.get(Skill, skill_a_id)
            assert skill.name == fm_a
    finally:
        await _cleanup(int(a["id"]))
        await _cleanup(int(b["id"]))


@pytest.mark.asyncio
async def test_restore_version_renames_back():
    """撤回到无激活版本 → restore 重激活，主表 name 随版本 frontmatter 回写。

    yanked 态直造（撤回入口在 lifecycle projection 层，不在本测试范围）。"""
    owner = await _owner_id()
    fm = f"rs{uuid.uuid4().hex[:10]}"
    fm2 = f"rt{uuid.uuid4().hex[:10]}"
    created = await _create(owner, name="", fm_name=fm)
    skill_id = int(created["id"])
    try:
        v2 = await skill_service.create_version(
            _session(),
            skill_id,
            version="8.8.8",
            zip_content=_zip_bytes(fm2),
            zip_filename="v2.zip",
            created_by=owner,
        )
        await skill_service.activate_version(_session(), skill_id, int(v2["id"]))
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            v2row = await s.get(SkillVersion, int(v2["id"]))
            v2row.lifecycle_status = "yanked"
            v2row.is_active = False
            skill.current_version_id = None
            await s.commit()
        await skill_service.restore_version(_session(), skill_id, int(v2["id"]))
        async with _session() as s:
            skill = await s.get(Skill, skill_id)
            assert skill.name == fm2
            assert skill.current_version_id == int(v2["id"])
    finally:
        await _cleanup(skill_id)
