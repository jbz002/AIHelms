"""发布门控设置 repository（模块 07）。

单例表（id 固定为 1），不存在时自动初始化。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from models.db import PublishSettings


async def get_settings(session: AsyncSession) -> PublishSettings:
    settings = await session.get(PublishSettings, 1)
    if settings:
        return settings
    settings = PublishSettings(id=1)
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings
