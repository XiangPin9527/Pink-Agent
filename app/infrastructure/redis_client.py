import asyncio

import redis.asyncio as redis
from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_redis: redis.Redis | None = None
_redis_lock = asyncio.Lock()

REDIS_SOCKET_CONNECT_TIMEOUT = 5
REDIS_SOCKET_TIMEOUT = 10


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        async with _redis_lock:
            if _redis is None:
                settings = get_settings()
                _redis = redis.Redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    max_connections=20,
                    socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT,
                    socket_timeout=REDIS_SOCKET_TIMEOUT,
                )
                logger.info(
                    "Redis 连接池初始化完成",
                    redis_url=settings.redis_url,
                    connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT,
                    socket_timeout=REDIS_SOCKET_TIMEOUT,
                )
    return _redis


async def close_redis():
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis 连接池已关闭")


__all__ = ["get_redis", "close_redis"]
