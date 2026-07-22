"""Skill 版本漂移检测（S9）。

前序 04 声明了 drift 字段但无任何代码写入。本服务补落地：
- check_single_drift：单个 url 源 active 版本重算 hash 比对、回写 drift 字段。
- check_drift_batch：定时任务批量入口，逐版本独立持锁、单失败隔离。
- resync_as_new_version：漂移后把当前源内容作为新版本入库（inactive，走既有审查→激活门控）。

并发幂等靠 Redis 分布式锁（version 级），覆盖 Celery 定时与 admin 手动两种触发。
外链拉取必走 translate_repo_url → validate_url(default) → httpx 三步 SSRF 链路（与 create_skill 一致）。
拉取失败只记 drift_check_error + last_drift_check_at，不污染 drift_detected 语义。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from core.distributed_lock import redis_lock
from core.url_safety import validate_url
from core.url_translator import translate_repo_url
from exceptions import ConflictError, LockBusyError, NotFoundError, ValidationError
from repositories import skill_version_repo
from services import skill_content_service, skill_service
from services.skill_serializers import _serialize_version

logger = logging.getLogger(__name__)

# 检测/重同步锁 TTL：下载 60s（httpx 超时）+ hash 1s + 余量。批次串行不重叠。
DRIFT_LOCK_TTL = 300


def _compute_drifted_files(
    stored: dict[str, dict], fresh: dict[str, dict]
) -> list[str]:
    """对比新旧 file_hashes，返回内容发生变化的文件 path 列表。

    只比 sha256（内容指纹）。size 变化必伴随 sha256 变化；content_type/category
    是协议校验注入的元数据，与内容漂移无关，故仅元数据差异不计入。
    """
    stored = stored or {}
    fresh = fresh or {}
    drifted: list[str] = []
    for path, new_info in fresh.items():
        old_info = stored.get(path)
        if old_info is None:
            drifted.append(path)  # 新增文件
            continue
        if old_info.get("sha256") != new_info.get("sha256"):
            drifted.append(path)  # 内容变更
    for path in stored:
        if path not in fresh:
            drifted.append(path)  # 删除文件
    return drifted


def _bump_patch_version(current: str) -> str:
    """语义化版本末位 +1：1.2.3 → 1.2.4。非标准 semver 抛 ValidationError。"""
    parts = current.split(".")
    if len(parts) < 3:
        raise ValidationError(
            f"当前版本号 '{current}' 非语义化版本，无法自动递增，请手动指定"
        )
    try:
        patch = int(parts[-1])
    except ValueError:
        raise ValidationError(
            f"当前版本号 '{current}' 末位非数字，无法自动递增，请手动指定"
        )
    parts[-1] = str(patch + 1)
    return ".".join(parts)


async def _next_available_version(
    session: AsyncSession, skill_id: int, base_version: str, max_attempts: int = 5
) -> str:
    """从 base_version bump patch，冲突则继续 +1，最多 max_attempts 次。全占用抛 ConflictError。"""
    candidate = _bump_patch_version(base_version)
    for _ in range(max_attempts):
        existing = await skill_version_repo.find_next_version_candidate(
            session, skill_id, candidate
        )
        if existing is None:
            return candidate
        candidate = _bump_patch_version(candidate)
    raise ConflictError(f"自动递增版本号 {max_attempts} 次均冲突，请手动指定版本号")


async def _fetch_url_zip(source_url: str) -> bytes:
    """SSRF fail-closed 三步链路拉取：translate → validate(default) → httpx 下载。"""
    translated = translate_repo_url(source_url)
    validate_url(translated.download_url, profile="default")
    zip_bytes, _ = await skill_service._download_from_url(translated.download_url)
    return zip_bytes


async def check_single_drift(session: AsyncSession, version_id: int) -> dict:
    """检测单个版本漂移并回写。

    流程：取 version 级 Redis 锁 → SSRF 下载 → _compute_hashes 重算 → diff
          → update_drift_status 回写 → 返回刷新后的版本 dict。
    source_type != 'url' 抛 ValidationError；锁占用抛 LockBusyError（router→409）；
    下载/SSRF/包异常写 drift_check_error（不标 drift）后抛 ValidationError。
    """
    version = await skill_version_repo.find_by_id(session, version_id)
    if version is None:
        raise NotFoundError("skill_version", version_id)
    if version.source_type != "url":
        raise ValidationError("该版本非外链源，跳过漂移检测")

    async with redis_lock(f"aihelms:lock:skill_drift:{version_id}", ttl=DRIFT_LOCK_TTL):
        try:
            zip_bytes = await _fetch_url_zip(version.source_url)
        except ValidationError:
            await _record_check_failure(session, version_id, "源 URL 校验或拉取失败")
            raise
        except Exception as exc:  # httpx 超时 / HTTPStatusError / 解压异常
            logger.warning("drift fetch failed version_id=%s: %s", version_id, exc)
            await _record_check_failure(session, version_id, f"下载失败: {exc}")
            raise ValidationError(f"下载失败: {exc}") from exc

        new_composite, new_hashes = skill_content_service._compute_hashes(zip_bytes)
        drifted = _compute_drifted_files(version.file_hashes, new_hashes)
        drift_detected = new_composite != version.composite_hash or len(drifted) > 0
        await skill_version_repo.update_drift_status(
            session,
            version_id,
            drift_detected=drift_detected,
            drifted_files=drifted,
            check_error="",
        )
        await session.commit()
        await session.refresh(version)
        return _serialize_version(version)


async def _record_check_failure(
    session: AsyncSession, version_id: int, reason: str
) -> None:
    """拉取失败：不标 drift，记 drift_check_error + last_drift_check_at。"""
    await skill_version_repo.update_drift_status(
        session,
        version_id,
        drift_detected=False,
        drifted_files=[],
        check_error=reason,
    )
    await session.commit()


async def check_drift_batch(session: AsyncSession, limit: int = 100) -> dict:
    """定时任务批量入口。逐版本独立持锁，单版本失败/锁忙不影响其它。"""
    versions = await skill_version_repo.list_url_active(session, limit=limit)
    checked = drifted = failed = skipped = 0
    for v in versions:
        try:
            result = await check_single_drift(session, v.id)
            checked += 1
            if result.get("drift_detected"):
                drifted += 1
        except LockBusyError:
            skipped += 1
        except Exception:
            logger.exception("drift check failed version_id=%s", v.id)
            await session.rollback()
            failed += 1
    logger.info(
        "skill drift batch done: checked=%d drifted=%d failed=%d skipped=%d",
        checked,
        drifted,
        failed,
        skipped,
    )
    return {
        "checked": checked,
        "drifted": drifted,
        "failed": failed,
        "skipped": skipped,
    }


async def resync_as_new_version(
    session: AsyncSession,
    version_id: int,
    *,
    new_version: str | None = None,
    created_by: int | None,
) -> dict:
    """把漂移版本当前源内容作为新版本入库（inactive + not_scanned，不自动激活）。

    版本号：显式指定则校验未占用；否则自动 patch +1（冲突重试）。
    源类型 lineage 保留 url：新版本 source_type='url'、source_url 沿用，后续仍参与漂移检测。
    """
    version = await skill_version_repo.find_by_id(session, version_id)
    if version is None:
        raise NotFoundError("skill_version", version_id)
    if version.source_type != "url":
        raise ValidationError("该版本非外链源，无法重新同步")

    async with redis_lock(f"aihelms:lock:skill_drift:{version_id}", ttl=DRIFT_LOCK_TTL):
        zip_bytes = await _fetch_url_zip(version.source_url)
        if new_version:
            target = new_version
            clash = await skill_version_repo.find_next_version_candidate(
                session, version.skill_id, target
            )
            if clash is not None:
                raise ConflictError(f"版本号 '{target}' 已存在")
        else:
            target = await _next_available_version(
                session, version.skill_id, version.version
            )
        return await skill_service.create_version(
            session,
            version.skill_id,
            version=target,
            version_label=f"重新同步自 {version.version}",
            change_log=f"漂移重新同步：源 {version.source_url} 内容已变更",
            zip_content=zip_bytes,
            zip_filename=version.zip_filename or "skill.zip",
            source="manual",
            source_url=version.source_url,
            created_by=created_by,
        )
