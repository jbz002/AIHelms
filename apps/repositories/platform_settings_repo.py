"""平台设置 repository（单例，id 固定为 1，不存在时自动初始化）。"""

from sqlalchemy.ext.asyncio import AsyncSession

from models.db import PlatformSettings


async def get_settings(session: AsyncSession) -> PlatformSettings:
    settings = await session.get(PlatformSettings, 1)
    if settings:
        return settings
    settings = PlatformSettings(id=1)
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings
