"""版本生命周期共享逻辑：单 active 激活、弃用。

MCP 与 Skill 版本管理共用本模块，保证「激活时先同步外部系统（LiteLLM）成功，
再翻转 DB active」这一关键顺序只有一份实现（零不一致窗口）。资源特定行为
（LiteLLM 同步、运行时快照拷贝）通过回调注入。
"""

import logging
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ValidationError

logger = logging.getLogger(__name__)


async def activate_version(
    session: AsyncSession,
    version,
    master,
    parent_id: int,
    repo,
    on_sync: Callable[..., Awaitable[None]],
    apply_snapshot: Callable[..., Awaitable[None]],
) -> None:
    """单 active 激活，零不一致窗口。

    顺序：
      1. on_sync(master, version) — 同步外部系统；失败则抛出，DB active 不翻转。
      2. deactivate_others → set_active — 必须先降级其它 active 再激活目标，
         维持部分唯一索引 uq_*_active 的单 active 不变式。
      3. master.current_version_id = version.id + apply_snapshot 拷贝运行时快照。
      4. 提交。
    """
    await on_sync(master, version)
    await repo.deactivate_others(session, parent_id, version.id)
    await repo.set_active(session, version.id)
    master.current_version_id = version.id
    await apply_snapshot(master, version)
    await session.commit()


async def deprecate(
    session: AsyncSession,
    version,
    repo,
    sunset_date: datetime | None,
) -> None:
    """弃用版本。守卫：active 版本不可直接弃用（需先切换到其它版本）。"""
    if version.is_active:
        raise ValidationError("需先切换到其他版本再弃用")
    await repo.mark_deprecated(session, version.id, sunset_date)
    await session.commit()
