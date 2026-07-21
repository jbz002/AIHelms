"""Redis 分布式锁。

用于重算类操作（评分聚合、搜索重建、漂移批量检测）防并发重算。
SET key token NX EX ttl 抢锁；Lua 脚本校验 token 释放，防误删他人锁。
"""

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from redis.asyncio import Redis

from core.config import settings
from core.redis_client import get_redis
from exceptions import LockBusyError

logger = logging.getLogger(__name__)

# 校验 token 后再删除，避免释放他人锁（超时后被另一进程接管的场景）
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


@asynccontextmanager
async def redis_lock(
    key: str,
    ttl: int | None = None,
):
    """抢分布式锁；抢不到抛 LockBusyError。

    用法：
        async with redis_lock("aihelms:lock:rating:skill:1"):
            ...  # 临界区
    """
    if ttl is None:
        ttl = settings.distributed_lock_default_ttl
    client: Redis = get_redis()
    token = uuid4().hex
    acquired = await client.set(key, token, nx=True, ex=ttl)
    if not acquired:
        raise LockBusyError(key)
    try:
        yield
    finally:
        try:
            await client.eval(_RELEASE_SCRIPT, 1, key, token)
        except Exception:  # noqa: BLE001
            logger.warning("release distributed lock failed: %s", key, exc_info=True)
