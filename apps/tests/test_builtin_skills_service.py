"""内置 Skills 开箱即用单测（S8）。

纯函数部分（sha256 / load_manifest / fetch 白名单与防穿越）无需中间件即可跑；
sync_single / sync_all 走真实 DB（依赖 dev 中间件），mock _fetch_zip 隔离文件系统。
"""

import hashlib
import io
import os
import shutil
import uuid
import zipfile
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete

from core.config import settings
from core.database import get_worker_session_factory
from exceptions import ValidationError
from models.db import Skill, SkillVersion
from repositories import skill_label_repo, skill_repo, skill_version_repo
from services import builtin_skills_service

_BUILTIN_SLUGS = {"code-review", "doc-summary", "meeting-notes"}


def _session():
    return get_worker_session_factory()()


def _make_zip(slug: str, body: str = "test skill body") -> bytes:
    """构造合法 zip（含 SKILL.md），过 S5 包校验 + S1 协议校验。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{slug}/SKILL.md",
            f"---\nname: {slug}\ndescription: test skill\n---\n# {slug}\n\n{body}\n",
        )
    return buf.getvalue()


def _entry(slug: str, version: str = "1.0.0", sha: str | None = None) -> dict:
    return {
        "slug": slug,
        "name": slug,
        "version": version,
        "category": "dev",
        "description": "test",
        "sha256": sha or "x" * 64,
        "path": "",
        "url": "",
    }


async def _cleanup(skill_ids: list[int]) -> None:
    async with _session() as s:
        for sid in skill_ids:
            versions = await skill_version_repo.list_versions(s, sid)
            skill = await skill_repo.find_by_id(s, sid)
            paths = {v.zip_path for v in versions if v.zip_path}
            if skill and skill.zip_path:
                paths.add(skill.zip_path)
            for path in paths:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            if skill:
                version_dir = os.path.join(settings.skills_storage_dir, skill.skill_id)
                if os.path.isdir(version_dir):
                    shutil.rmtree(version_dir, ignore_errors=True)
        await s.execute(
            delete(SkillVersion).where(SkillVersion.skill_id.in_(skill_ids))
        )
        await s.execute(delete(Skill).where(Skill.id.in_(skill_ids)))
        await s.commit()


# ─── 纯函数 ──────────────────────────────────────────────────────────────────


def test_verify_sha256_match():
    data = b"hello-builtin"
    builtin_skills_service._verify_sha256(data, hashlib.sha256(data).hexdigest())


def test_verify_sha256_mismatch_raises():
    with pytest.raises(ValidationError):
        builtin_skills_service._verify_sha256(b"abc", "0" * 64)


def test_load_manifest_reads_bundled():
    entries = builtin_skills_service.load_manifest()
    assert len(entries) == 3
    assert {e["slug"] for e in entries} == _BUILTIN_SLUGS
    for e in entries:
        assert len(e["sha256"]) == 64
        assert e["path"] or e["url"]


def test_load_manifest_rejects_bad_slug(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '[{"slug":"Bad Slug","version":"1.0.0","sha256":"'
        + "a" * 64
        + '","path":"x.zip"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(builtin_skills_service, "_manifest_path", lambda: manifest)
    with pytest.raises(ValidationError):
        builtin_skills_service.load_manifest()


@pytest.mark.asyncio
async def test_fetch_zip_path_traversal_rejected():
    with pytest.raises(ValidationError):
        await builtin_skills_service._fetch_zip(
            _entry("x", sha="a" * 64) | {"path": "../etc/passwd"}
        )


@pytest.mark.asyncio
async def test_fetch_zip_url_no_whitelist_rejected(monkeypatch):
    monkeypatch.setattr(settings, "builtin_skills_allowed_domains", "")
    with pytest.raises(ValidationError):
        await builtin_skills_service._fetch_zip(
            _entry("x", sha="a" * 64) | {"url": "https://cdn.example.com/a.zip"}
        )


@pytest.mark.asyncio
async def test_fetch_zip_url_not_in_whitelist_rejected(monkeypatch):
    monkeypatch.setattr(settings, "builtin_skills_allowed_domains", "allowed.cdn.com")
    with pytest.raises(ValidationError):
        await builtin_skills_service._fetch_zip(
            _entry("x", sha="a" * 64) | {"url": "https://evil.example.com/a.zip"}
        )


# ─── sync_single / sync_all（真实 DB + mock fetch）────────────────────────────


@pytest.mark.asyncio
async def test_sync_single_creates_skill_and_grants_official():
    slug = f"test-builtin-{uuid.uuid4().hex[:8]}"
    zip_bytes = _make_zip(slug)
    entry = _entry(slug, sha=hashlib.sha256(zip_bytes).hexdigest())
    with patch.object(
        builtin_skills_service, "_fetch_zip", new=AsyncMock(return_value=zip_bytes)
    ):
        async with _session() as s:
            res = await builtin_skills_service.sync_single(s, entry)
            skill_id = res["skill_id"]
    try:
        assert res["action"] == "created"
        async with _session() as s:
            skill = await skill_repo.find_by_id(s, skill_id)
            assert skill is not None
            assert skill.is_builtin is True
            assert skill.builtin_slug == slug
            assert skill.is_published is True
            labels = await skill_label_repo.list_by_skill(s, skill_id)
            assert any(lb["name"] == "official" for lb in labels)
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_sync_single_idempotent_skip():
    slug = f"test-builtin-{uuid.uuid4().hex[:8]}"
    zip_bytes = _make_zip(slug)
    entry = _entry(slug, sha=hashlib.sha256(zip_bytes).hexdigest())
    with patch.object(
        builtin_skills_service, "_fetch_zip", new=AsyncMock(return_value=zip_bytes)
    ):
        async with _session() as s:
            r1 = await builtin_skills_service.sync_single(s, entry)
            skill_id = r1["skill_id"]
        async with _session() as s:
            r2 = await builtin_skills_service.sync_single(s, entry)
    try:
        assert r1["action"] == "created"
        assert r2["action"] == "skipped"
        assert r2["skill_id"] == skill_id
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_sync_single_version_upgrade_activates_new():
    slug = f"test-builtin-{uuid.uuid4().hex[:8]}"
    zip_bytes = _make_zip(slug, "v1 body")
    entry_v1 = _entry(slug, "1.0.0", sha=hashlib.sha256(zip_bytes).hexdigest())
    zip_bytes_v2 = _make_zip(slug, "v2 different body")
    entry_v2 = _entry(slug, "1.1.0", sha=hashlib.sha256(zip_bytes_v2).hexdigest())
    with patch.object(
        builtin_skills_service,
        "_fetch_zip",
        new=AsyncMock(side_effect=[zip_bytes, zip_bytes_v2]),
    ):
        async with _session() as s:
            r1 = await builtin_skills_service.sync_single(s, entry_v1)
            skill_id = r1["skill_id"]
        async with _session() as s:
            r2 = await builtin_skills_service.sync_single(s, entry_v2)
    try:
        assert r1["action"] == "created"
        assert r2["action"] == "version_added"
        async with _session() as s:
            active = await skill_version_repo.find_active_for_skill(s, skill_id)
            assert active is not None
            assert active.version == "1.1.0"
            assert active.lifecycle_status == "published"
    finally:
        await _cleanup([skill_id])


@pytest.mark.asyncio
async def test_sync_all_failure_isolation():
    slug_a = f"test-builtin-{uuid.uuid4().hex[:8]}"
    slug_b = f"test-builtin-{uuid.uuid4().hex[:8]}"
    zip_bytes = _make_zip(slug_a)
    entries = [
        _entry(slug_a, sha=hashlib.sha256(zip_bytes).hexdigest()),
        _entry(slug_b, sha="0" * 64),  # sha 不匹配 → 失败
    ]
    created_ids: list[int] = []
    with (
        patch.object(
            builtin_skills_service, "_fetch_zip", new=AsyncMock(return_value=zip_bytes)
        ),
        patch.object(builtin_skills_service, "load_manifest", return_value=entries),
    ):
        async with _session() as s:
            result = await builtin_skills_service.sync_all(s)
            for slug in (slug_a, slug_b):
                skill = await skill_repo.find_by_builtin_slug(s, slug)
                if skill is not None:
                    created_ids.append(skill.id)
    try:
        assert result["synced"] == 1
        assert len(result["failed"]) == 1
        assert result["failed"][0]["slug"] == slug_b
        assert len(created_ids) == 1  # 仅成功的入库
    finally:
        await _cleanup(created_ids)
