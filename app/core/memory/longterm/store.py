import asyncio

from langchain_openai import OpenAIEmbeddings
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg_pool import AsyncConnectionPool

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_pool: AsyncConnectionPool | None = None
_store: AsyncPostgresStore | None = None
_lock = asyncio.Lock()


async def get_longterm_store() -> AsyncPostgresStore:
    """
    Long-term memory vector store (langgraph AsyncPostgresStore).

    This is used by MQ workers and should be initialized once and reused
    to avoid connection storms and repeated setup work.
    """
    global _pool, _store
    if _store is not None:
        return _store

    async with _lock:
        if _store is not None:
            return _store

        settings = get_settings()

        async def _configure_conn(conn):
            await conn.set_autocommit(True)

        _pool = AsyncConnectionPool(
            conninfo=settings.database_url.replace("+asyncpg", ""),
            min_size=1,
            max_size=5,
            configure=_configure_conn,
        )
        await _pool.open()

        embedder = OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            dimensions=settings.openai_embedding_dims,
            check_embedding_ctx_length=False,
        )

        _store = AsyncPostgresStore(
            conn=_pool,
            index={
                "dims": settings.openai_embedding_dims,
                "embed": embedder,
                "fields": ["content", "category"],
            },
        )
        await _store.setup()

        logger.info("长期记忆 Store 初始化完成", dims=settings.openai_embedding_dims)
        return _store


async def close_longterm_store() -> None:
    global _pool, _store
    async with _lock:
        _store = None
        if _pool is not None:
            try:
                await _pool.close()
            finally:
                _pool = None


__all__ = ["get_longterm_store", "close_longterm_store"]

