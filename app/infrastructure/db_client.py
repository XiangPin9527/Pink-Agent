import asyncio

import asyncpg
from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_db_pool: asyncpg.Pool | None = None
_db_pool_lock = asyncio.Lock()


def _normalize_dsn(dsn: str) -> str:
    return dsn.replace("+asyncpg", "")


async def get_db_pool() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None:
        async with _db_pool_lock:
            if _db_pool is None:
                settings = get_settings()
                dsn = _normalize_dsn(settings.database_url)
                _db_pool = await asyncpg.create_pool(
                    dsn,
                    min_size=5,
                    max_size=settings.database_pool_size,
                )
                logger.info("PostgreSQL 连接池初始化完成", dsn=dsn.split("@")[-1] if "@" in dsn else dsn)
    return _db_pool


async def close_db_pool():
    global _db_pool
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None
        logger.info("PostgreSQL 连接池已关闭")


__all__ = ["get_db_pool", "close_db_pool"]
