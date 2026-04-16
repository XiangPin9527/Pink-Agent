import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config.settings import get_settings
from app.utils.logger import setup_logging, get_logger

setup_logging(level="INFO", format="console")
logger = get_logger(__name__)

CHECKPOINT_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint BYTEA NOT NULL,
    metadata BYTEA,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
"""

CHECKPOINT_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread
    ON checkpoints(thread_id, checkpoint_ns);

CREATE INDEX IF NOT EXISTS idx_checkpoints_created
    ON checkpoints(thread_id, created_at DESC);
"""

USER_INSTRUCTION_DDL = """
CREATE TABLE IF NOT EXISTS user_instructions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL UNIQUE,
    instruction_content TEXT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_instructions_user_id
    ON user_instructions(user_id);
"""


async def init_database():
    import asyncpg

    settings = get_settings()
    dsn = settings.database_url.replace("+asyncpg", "")
    logger.info("开始初始化数据库", dsn=dsn)

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        logger.info("pgvector 扩展已确认")

        async with conn.transaction():
            await conn.execute(CHECKPOINT_DDL)
        logger.info("Checkpoint 表创建完成")

        await conn.execute(CHECKPOINT_INDEX_DDL)
        logger.info("Checkpoint 索引创建完成")

        async with conn.transaction():
            await conn.execute(USER_INSTRUCTION_DDL)
        logger.info("User Instructions 表创建完成")

        logger.info("code_vectors 表将由 PGVectorStore 在应用启动时自动创建")
    finally:
        await conn.close()


async def init_store():
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from langchain_openai import OpenAIEmbeddings
    from psycopg_pool import AsyncConnectionPool

    settings = get_settings()

    async def _configure_conn(conn):
        await conn.set_autocommit(True)

    pg_pool = AsyncConnectionPool(
        conninfo=settings.database_url.replace("+asyncpg", ""),
        min_size=1,
        max_size=2,
        configure=_configure_conn,
    )
    await pg_pool.open()

    embedder = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        dimensions=settings.openai_embedding_dims,
        check_embedding_ctx_length=False,
    )
    store = AsyncPostgresStore(
        conn=pg_pool,
        index={
            "dims": settings.openai_embedding_dims,
            "embed": embedder,
            "fields": ["content", "category"],
        },
    )
    await store.setup()
    logger.info("Store 表创建完成")

    import asyncpg
    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        store_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE tablename = 'store')"
        )
        vectors_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE tablename = 'store_vectors')"
        )
        logger.info(
            "数据库表状态检查",
            store_table=store_exists,
            store_vectors_table=vectors_exists,
        )

        if vectors_exists:
            cols = await conn.fetch(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'store_vectors' ORDER BY ordinal_position"
            )
            logger.info("store_vectors 表结构", columns=[dict(c) for c in cols])
        else:
            logger.warning("store_vectors 表未创建，请检查 vector_migrations 版本")
            vm_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE tablename = 'vector_migrations')"
            )
            if vm_exists:
                rows = await conn.fetch("SELECT v FROM vector_migrations ORDER BY v")
                logger.info("vector_migrations 版本记录", versions=[r["v"] for r in rows])
            else:
                logger.warning("vector_migrations 表不存在")
    finally:
        await conn.close()

    await pg_pool.close()


async def main():
    await init_database()
    await init_store()
    logger.info("数据库初始化全部完成")


if __name__ == "__main__":
    asyncio.run(main())
