"""S4 · Skill 版本别名 Tag 服务。

- 用户 tag（beta/stable）：指向具体 version_id，可创建/移动/删除。
- latest 系统保留只读：由 refresh_latest_tag 在 publish/yank 时按「最新 published」推导，
  口径与 skill_version_repo.find_latest_published（id desc）一致。
"""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError, ValidationError
from models.db import SkillTag
from repositories import skill_repo, skill_tag_repo, skill_version_repo

logger = logging.getLogger(__name__)

LATEST_TAG = "latest"
_TAG_NAME_RE = re.compile(r"^[a-z0-9_.-]{1,32}$")


def _serialize_tag(t: SkillTag) -> dict:
    return {
        "id": t.id,
        "skill_id": t.skill_id,
        "tag_name": t.tag_name,
        "version_id": t.version_id,
        "is_system": t.is_system,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


async def list_tags(session: AsyncSession, skill_id: int) -> list[dict]:
    await _require_skill(session, skill_id)
    tags = await skill_tag_repo.find_by_skill(session, skill_id)
    return [_serialize_tag(t) for t in tags]


async def create_or_move_tag(
    session: AsyncSession,
    skill_id: int,
    tag_name: str,
    version_id: int,
    actor_id: int | None = None,
) -> dict:
    tag_name = (tag_name or "").strip()
    if tag_name == LATEST_TAG:
        raise ValidationError("latest 为系统保留标签，不可手动指定")
    if not _TAG_NAME_RE.match(tag_name):
        raise ValidationError("标签名仅支持小写字母、数字及 _ . -，长度 1-32")
    await _require_skill(session, skill_id)
    version = await skill_version_repo.find_by_id(session, version_id)
    if not version or version.skill_id != skill_id:
        raise NotFoundError("version", version_id)

    tag = await skill_tag_repo.upsert(
        session, skill_id, tag_name, version_id, is_system=False
    )
    await session.commit()
    logger.info(
        "skill tag upserted",
        extra={"skill_id": skill_id, "tag_name": tag_name, "version_id": version_id},
    )
    return _serialize_tag(tag)


async def delete_tag(session: AsyncSession, skill_id: int, tag_name: str) -> None:
    tag = await skill_tag_repo.find_by_skill_and_name(session, skill_id, tag_name)
    if not tag:
        raise NotFoundError("tag", tag_name)
    if tag.is_system:
        raise ValidationError("系统保留标签不可删除")
    await skill_tag_repo.delete_by_skill_and_name(session, skill_id, tag_name)
    await session.commit()


async def refresh_latest_tag(session: AsyncSession, skill_id: int) -> None:
    """latest = 最新 published 版本（id desc）。无 published 则清除 latest 指针。

    在生命周期提交之后调用，内部自行提交。与 yank 指针重算口径一致。
    """
    latest = await skill_version_repo.find_latest_published(session, skill_id)
    if latest:
        await skill_tag_repo.upsert(
            session, skill_id, LATEST_TAG, latest.id, is_system=True
        )
    else:
        await skill_tag_repo.delete_system_latest(session, skill_id)
    await session.commit()


async def _require_skill(session: AsyncSession, skill_id: int) -> None:
    skill = await skill_repo.find_by_id(session, skill_id)
    if not skill:
        raise NotFoundError("skill", skill_id)
