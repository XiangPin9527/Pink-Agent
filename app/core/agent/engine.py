"""
Orchestrator 执行引擎

编排引擎：基于 LangGraph StateGraph 的路由 + 简单/复杂双路径架构，
集成 Checkpoint + Store 记忆系统 + SummarizationMiddleware + MQService
"""
from psycopg_pool import AsyncConnectionPool
from langchain_openai import OpenAIEmbeddings
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.config.settings import get_settings
from app.core.memory.checkpoint.saver import RedisPostgresSaver
from app.core.memory.loader import MemoryLoader
from app.core.memory.longterm.extractor import LongTermExtractor
from app.core.memory.mq import (
    get_mq_service_instance,
    QUEUE_CHECKPOINT_PERSIST,
    QUEUE_CHECKPOINT_WRITES,
    QUEUE_LONGTERM,
    QUEUE_SHORTMEM_COMPRESS,
)
from app.core.memory.mq.handlers import (
    handle_checkpoint_persist,
    handle_checkpoint_writes,
    handle_longterm_extract,
    handle_shortmem_compress,
)
from app.core.llm.service import get_llm_service
from app.core.orchestrator.graph import build_orchestrator_graph
from app.core.orchestrator.memory import set_orchestrator_components
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def create_orchestrator_engine():
    """创建编排引擎（路由+简单/复杂双路径，带完整记忆系统）"""
    from app.tools.mcp.manager import initialize_mcp

    settings = get_settings()

    try:
        await initialize_mcp()
        logger.info("MCP 服务初始化完成")
    except Exception as e:
        logger.warning("MCP 服务初始化失败，将不使用 MCP 工具", error=str(e))

    checkpointer = RedisPostgresSaver()

    embedder = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        dimensions=settings.openai_embedding_dims,
        check_embedding_ctx_length=False,
    )

    async def _configure_conn(conn):
        await conn.set_autocommit(True)

    pg_pool = AsyncConnectionPool(
        conninfo=settings.database_url.replace("+asyncpg", ""),
        min_size=2,
        max_size=10,
        configure=_configure_conn,
    )
    await pg_pool.open()

    store = AsyncPostgresStore(
        conn=pg_pool,
        index={
            "dims": settings.openai_embedding_dims,
            "embed": embedder,
            "fields": ["content", "category"],
        },
    )
    await store.setup()

    memory_loader = MemoryLoader(store=store)

    llm = get_llm_service().get_model()
    longterm_extractor = LongTermExtractor(llm=llm, store=store)

    mq_service = await get_mq_service_instance()

    mq_service.register_handler(QUEUE_CHECKPOINT_PERSIST, handle_checkpoint_persist)
    mq_service.register_handler(QUEUE_CHECKPOINT_WRITES, handle_checkpoint_writes)
    mq_service.register_handler(
        QUEUE_LONGTERM,
        lambda body: handle_longterm_extract(longterm_extractor, body),
    )
    mq_service.register_handler(QUEUE_SHORTMEM_COMPRESS, handle_shortmem_compress)

    await mq_service.start_workers()

    set_orchestrator_components(memory_loader=memory_loader, mq_service=mq_service)

    graph = build_orchestrator_graph()
    compiled_graph = graph.compile(checkpointer=checkpointer, store=store)

    logger.info(
        "OrchestratorEngine 创建完成",
        has_checkpointer=True,
        has_store=True,
        has_memory_loader=True,
        has_mq_service=True,
    )

    return compiled_graph


__all__ = [
    "create_orchestrator_engine",
]
