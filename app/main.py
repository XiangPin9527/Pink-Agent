"""
FastAPI 应用入口
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config.settings import get_settings
from app.utils.logger import setup_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(level=settings.log_level, format=settings.log_format)
    logger = get_logger(__name__)

    logger.info("应用启动中...")

    from app.infrastructure.redis_client import get_redis
    from app.infrastructure.db_client import get_db_pool
    from app.infrastructure.mq_client import get_mq_connection

    try:
        await get_redis()
        logger.info("Redis 连接初始化完成")
    except Exception as e:
        logger.warning("Redis 连接初始化失败，部分功能不可用", error=str(e))

    try:
        await get_db_pool()
        logger.info("PostgreSQL 连接池初始化完成")
    except Exception as e:
        logger.warning("PostgreSQL 连接池初始化失败，部分功能不可用", error=str(e))

    try:
        await get_mq_connection()
        logger.info("RabbitMQ 连接初始化完成")
    except Exception as e:
        logger.warning("RabbitMQ 连接初始化失败，部分功能不可用", error=str(e))

    try:
        await _start_mq_workers()
        logger.info("MQ Workers 启动完成")
    except Exception as e:
        logger.warning("MQ Workers 启动失败，异步任务将不可用", error=str(e))

    yield

    logger.info("应用关闭中...")

    from app.infrastructure.redis_client import close_redis
    from app.infrastructure.db_client import close_db_pool
    from app.infrastructure.mq_client import close_mq
    from app.core.memory.mq.service import close_mq_service
    from app.api.deps import _agent_engine_with_memory

    try:
        await close_mq_service()
    except Exception as e:
        logger.warning("关闭 MQ Service 失败", error=str(e))

    if _agent_engine_with_memory is not None:
        await _agent_engine_with_memory.aclose()

    await close_mq()
    await close_redis()
    await close_db_pool()

    logger.info("应用已关闭")


async def _start_mq_workers():
    from app.core.memory.mq.service import get_mq_service_instance
    from app.core.memory.mq.handlers import (
        handle_checkpoint_persist,
        handle_checkpoint_writes,
        handle_longterm_extract,
        handle_shortmem_compress,
        handle_rag_ingest_repo,
        handle_rag_ingest_files,
    )
    from app.core.memory.mq import (
        QUEUE_CHECKPOINT_PERSIST,
        QUEUE_CHECKPOINT_WRITES,
        QUEUE_LONGTERM,
        QUEUE_SHORTMEM_COMPRESS,
        QUEUE_RAG_INGEST_REPO,
        QUEUE_RAG_INGEST_FILES,
    )

    mq_service = await get_mq_service_instance()

    mq_service.register_handler(QUEUE_CHECKPOINT_PERSIST, handle_checkpoint_persist)
    mq_service.register_handler(QUEUE_CHECKPOINT_WRITES, handle_checkpoint_writes)
    mq_service.register_handler(QUEUE_LONGTERM, handle_longterm_extract)
    mq_service.register_handler(QUEUE_SHORTMEM_COMPRESS, handle_shortmem_compress)
    mq_service.register_handler(QUEUE_RAG_INGEST_REPO, handle_rag_ingest_repo)
    mq_service.register_handler(QUEUE_RAG_INGEST_FILES, handle_rag_ingest_files)

    await mq_service.start_workers()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI Agent Engine - 基于 LangChain + LangGraph 的多步推理 Agent 执行引擎",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins if hasattr(settings, "cors_origins") else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.debug,
    )
