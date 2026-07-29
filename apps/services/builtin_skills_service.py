"""S8 · 内置 Skills 开箱即用。

启动时按 manifest 异步同步一批官方 skill 到全局，复用标准发布链路（create_skill /
create_version + 协议/包校验），开箱即用。

源支持双模式：
- path：本地打包 zip（apps/builtin_skills/skills/），开箱零外部依赖。
- url：远程源，须域名白名单（BUILTIN_SKILLS_ALLOWED_DOMAINS）+ url_safety SSRF 校验。

幂等：按 builtin_slug + version 查重；单条 Redis 锁防多实例/多 worker 并发重复。
安全：sha256 与 manifest 声明一致才入库（防中间人篡改）；单条失败不阻断其它。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.distributed_lock import redis_lock
from exceptions import LockBusyError, ValidationError
from models.db import User
from repositories import skill_repo, skill_version_repo
from services import skill_service

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILTIN_DIR = _REPO_ROOT / "apps" / "builtin_skills"
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
SYNC_LOCK_TTL = 300

BUILTIN_AUTHOR = "AIHelms"


# ─── manifest 加载与校验 ─────────────────────────────────────────────────────


def _manifest_path() -> Path:
    raw = settings.builtin_skills_manifest_path
    p = Path(raw)
    return p if p.is_absolute() else _REPO_ROOT / raw


def load_manifest() -> list[dict]:
    """读取内置 manifest 并做结构校验。非法条目抛 ValidationError（由 sync_all 隔离）。"""
    path = _manifest_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("builtin skills manifest not found: %s", path)
        return []
    except (OSError, json.JSONDecodeError):
        logger.exception("builtin skills manifest unreadable: %s", path)
        return []

    if not isinstance(data, list):
        logger.warning("builtin skills manifest not a list")
        return []

    entries: list[dict] = []
    for idx, raw_entry in enumerate(data):
        if not isinstance(raw_entry, dict):
            raise ValidationError(f"manifest[{idx}] 非对象")
        slug = str(raw_entry.get("slug", "")).strip()
        version = str(raw_entry.get("version", "")).strip()
        sha256 = str(raw_entry.get("sha256", "")).strip().lower()
        path_val = str(raw_entry.get("path", "")).strip()
        url_val = str(raw_entry.get("url", "")).strip()
        if not _SLUG_RE.match(slug):
            raise ValidationError(f"manifest[{idx}] slug 非法（需 kebab-case）: {slug}")
        if not version:
            raise ValidationError(f"manifest[{idx}] version 缺失")
        if len(sha256) != 64:
            raise ValidationError(f"manifest[{idx}] sha256 非法")
        if not path_val and not url_val:
            raise ValidationError(f"manifest[{idx}] 需提供 path 或 url")
        entries.append(
            {
                "slug": slug,
                "name": str(raw_entry.get("name") or slug).strip(),
                "version": version,
                "category": str(raw_entry.get("category") or "general").strip(),
                "description": str(raw_entry.get("description") or "").strip(),
                "sha256": sha256,
                "path": path_val,
                "url": url_val,
            }
        )
    return entries


# ─── 源拉取与校验 ────────────────────────────────────────────────────────────


def _allowed_domains() -> set[str]:
    raw = settings.builtin_skills_allowed_domains or ""
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


async def _fetch_zip(entry: dict) -> bytes:
    """按 path/url 模式拉取 zip bytes。path 防穿越；url 走域名白名单 + SSRF。"""
    path_val = entry["path"]
    if path_val:
        base = _BUILTIN_DIR.resolve()
        full = (base / path_val).resolve()
        try:
            full.relative_to(base)
        except ValueError:
            raise ValidationError(f"内置 skill path 越界: {path_val}")
        if not full.is_file():
            raise ValidationError(f"内置 skill 文件不存在: {path_val}")
        return full.read_bytes()

    # url 模式
    url = entry["url"]
    host = (urlparse(url).hostname or "").lower()
    allowed = _allowed_domains()
    if not allowed:
        raise ValidationError("未配置 BUILTIN_SKILLS_ALLOWED_DOMAINS，远程内置源禁用")
    if host not in allowed:
        raise ValidationError(f"内置源域名不在白名单: {host}")
    from core.url_safety import validate_url

    validate_url(url, profile="default")  # SSRF fail-closed
    zip_bytes, _ = await skill_service._download_from_url(url)
    return zip_bytes


def _verify_sha256(content: bytes, expected: str) -> None:
    actual = hashlib.sha256(content).hexdigest()
    if actual.lower() != expected.lower():
        raise ValidationError(
            f"内置 skill sha256 不一致（期望 {expected[:12]}…，实际 {actual[:12]}…）"
        )


# ─── super_admin 解析 ───────────────────────────────────────────────────────


async def _resolve_super_admin_id(session: AsyncSession) -> int | None:
    result = await session.execute(
        select(User).where(User.is_admin == True).limit(1)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning("no super_admin user found; builtin skills skip created_by")
    return user.id if user else None


# ─── 单条同步 ────────────────────────────────────────────────────────────────


async def _create_builtin_skill(
    session: AsyncSession, entry: dict, zip_bytes: bytes, admin_id: int | None
) -> dict:
    created = await skill_service.create_skill(
        session,
        name=entry["name"],
        icon="📦",
        description=entry["description"],
        category=entry["category"],
        version=entry["version"],
        author=BUILTIN_AUTHOR,
        agent_install_prompt="",
        usage_instructions="",
        is_published=False,
        requires_approval=False,
        visibility_type="all",
        zip_content=zip_bytes,
        zip_filename=f"{entry['slug']}-{entry['version']}.zip",
        created_by=admin_id,
    )
    skill_id = int(created["id"])
    # 结构化内置标记（独立列 is_builtin / builtin_slug）
    skill = await skill_repo.find_by_id(session, skill_id)
    if skill is not None:
        skill.is_builtin = True
        skill.builtin_slug = entry["slug"]
    await session.commit()
    # 绕过发布门控直接发布（等同审核通过路径）
    await skill_service.set_published(session, skill_id, True)
    await session.commit()
    return {"slug": entry["slug"], "action": "created", "skill_id": skill_id}


async def _add_builtin_version(
    session: AsyncSession,
    skill_id: int,
    entry: dict,
    zip_bytes: bytes,
    admin_id: int | None,
) -> dict:
    version_dict = await skill_service.create_version(
        session,
        skill_id,
        version=entry["version"],
        version_label=entry["name"],
        change_log=f"内置 skill 版本升级：{entry['version']}",
        zip_content=zip_bytes,
        zip_filename=f"{entry['slug']}-{entry['version']}.zip",
        source="builtin",
        created_by=admin_id,
    )
    version_id = int(version_dict["id"])
    # 内置版本直接激活（绕过安全/协议门控，内容由平台预审）
    await skill_service.activate_version_builtin(session, skill_id, version_id)
    return {"slug": entry["slug"], "action": "version_added", "skill_id": skill_id}


async def sync_single(session: AsyncSession, entry: dict) -> dict:
    """同步单个内置 skill 条目。幂等：slug+version 已存在则跳过。"""
    async with redis_lock(
        f"aihelms:lock:builtin_skill:{entry['slug']}", ttl=SYNC_LOCK_TTL
    ):
        zip_bytes = await _fetch_zip(entry)
        _verify_sha256(zip_bytes, entry["sha256"])
        admin_id = await _resolve_super_admin_id(session)

        existing = await skill_repo.find_by_builtin_slug(session, entry["slug"])
        if existing is None:
            return await _create_builtin_skill(session, entry, zip_bytes, admin_id)

        clash = await skill_version_repo.find_by_skill_and_version(
            session, existing.id, entry["version"]
        )
        if clash is not None:
            return {"slug": entry["slug"], "action": "skipped", "skill_id": existing.id}
        return await _add_builtin_version(
            session, existing.id, entry, zip_bytes, admin_id
        )


# ─── 批量入口（Celery 调用） ─────────────────────────────────────────────────


async def sync_all(session: AsyncSession) -> dict:
    """遍历 manifest 逐条同步。单条失败/锁忙隔离，整体不中断。"""
    if not settings.builtin_skills_enabled:
        logger.info("builtin skills disabled, skip sync")
        return {"synced": 0, "skipped": 0, "failed": []}

    try:
        entries = load_manifest()
    except Exception:  # noqa: BLE001
        logger.exception("builtin skills manifest invalid, abort sync")
        return {
            "synced": 0,
            "skipped": 0,
            "failed": [{"slug": "*", "error": "manifest 非法"}],
        }

    synced = skipped = 0
    failed: list[dict] = []
    for entry in entries:
        try:
            result = await sync_single(session, entry)
            if result["action"] == "skipped":
                skipped += 1
            else:
                synced += 1
            logger.info(
                "builtin skill sync %s: %s skill_id=%s",
                result["slug"],
                result["action"],
                result.get("skill_id"),
            )
        except LockBusyError:
            skipped += 1
            logger.info("builtin skill sync busy, skipped: %s", entry["slug"])
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            failed.append({"slug": entry["slug"], "error": str(exc)})
            logger.warning("builtin skill sync failed slug=%s: %s", entry["slug"], exc)
    logger.info(
        "builtin skills sync done: synced=%d skipped=%d failed=%d",
        synced,
        skipped,
        len(failed),
    )
    return {"synced": synced, "skipped": skipped, "failed": failed}


# ─── admin 状态查询 ──────────────────────────────────────────────────────────


async def build_status(session: AsyncSession) -> list[dict]:
    """manifest 条目与 DB 对比：哪些已同步、缺哪个版本。"""
    try:
        entries = load_manifest()
    except Exception:  # noqa: BLE001
        return []
    rows: list[dict] = []
    for entry in entries:
        skill = await skill_repo.find_by_builtin_slug(session, entry["slug"])
        version_present = False
        if skill is not None:
            clash = await skill_version_repo.find_by_skill_and_version(
                session, skill.id, entry["version"]
            )
            version_present = clash is not None
        rows.append(
            {
                "slug": entry["slug"],
                "name": entry["name"],
                "version": entry["version"],
                "category": entry["category"],
                "synced": version_present,
                "skill_id": skill.id if skill else None,
            }
        )
    return rows
