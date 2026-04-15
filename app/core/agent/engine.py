"""
Orchestrator 执行引擎

编排引擎：基于 LangGraph StateGraph 的路由 + 简单/复杂双路径架构，
集成 Checkpoint + Store 记忆系统 + SummarizationMiddleware + MQService
"""
from app.core.memory.checkpoint.saver import RedisPostgresSaver
from app.core.memory.loader import MemoryLoader
from app.core.memory.mq import get_mq_service_instance
from app.core.orchestrator.graph import build_orchestrator_graph
from app.core.orchestrator.memory import set_orchestrator_components
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def create_orchestrator_engine(store=None, mq_service=None):
    """创建编排引擎（路由+简单/复杂双路径，带完整记忆系统）"""
    from app.tools.mcp.manager import initialize_mcp
    from app.config.settings import get_settings
    from langchain_openai import OpenAIEmbeddings
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from psycopg_pool import AsyncConnectionPool

    settings = get_settings()

    try:
        await initialize_mcp()
        logger.info("MCP 服务初始化完成")
    except Exception as e:
        logger.warning("MCP 服务初始化失败，将不使用 MCP 工具", error=str(e))

    checkpointer = RedisPostgresSaver()

    if store is None:
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

    if mq_service is None:
        mq_service = await get_mq_service_instance()

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
