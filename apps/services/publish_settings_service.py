"""发布门控设置 service（模块 07）。

单例开关 publish_review_enabled：关 → 创建者直接发布（现状）；开 → 发布走评审。
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from repositories import publish_settings_repo


async def get_settings(session: AsyncSession) -> dict:
    s = await publish_settings_repo.get_settings(session)
    return {
        "publish_review_enabled": s.publish_review_enabled,
        "updated_by": s.updated_by,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


async def is_gate_enabled(session: AsyncSession) -> bool:
    """供资源 service 门控判断读取（不序列化）。"""
    s = await publish_settings_repo.get_settings(session)
    return bool(s.publish_review_enabled)


async def update_settings(
    session: AsyncSession, enabled: bool, current_user: dict
) -> dict:
    s = await publish_settings_repo.get_settings(session)
    s.publish_review_enabled = enabled
    s.updated_by = int(current_user["id"])
    s.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(s)
    return await get_settings(session)
