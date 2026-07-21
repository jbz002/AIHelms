"""Redis 客户端（按 event loop 缓存）。

供幂等加速、分布式锁、后续模块复用。基于 redis.asyncio（pyproject 已声明 redis>=5.0）。
连接串由 core/config.py 的 settings.redis_url 提供（redis://:pwd@host:port/0）。

redis.asyncio 连接绑定创建时的 event loop，跨 loop 复用会报 "Event loop is closed"。
按 running loop 缓存实例：生产单 loop = 一个单例；pytest 每测试新 loop 各自独立。
"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from core.config import settings

_redis_by_loop: dict[int, Redis] = {}


def get_redis() -> Redis:
    """返回当前 event loop 的 Redis 客户端（lazy 初始化）。"""
    loop = asyncio.get_running_loop()
    key = id(loop)
    client = _redis_by_loop.get(key)
    if client is None:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        _redis_by_loop[key] = client
    return client


async def close_redis() -> None:
    """应用关闭时释放所有 loop 的连接池。"""
    while _redis_by_loop:
        _, client = _redis_by_loop.popitem()
        await client.aclose()
