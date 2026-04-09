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

    yield

    logger.info("应用关闭中...")

    from app.infrastructure.redis_client import close_redis
    from app.infrastructure.db_client import close_db_pool
    from app.infrastructure.mq_client import close_mq
    from app.api.deps import _agent_engine_with_memory

    if _agent_engine_with_memory is not None:
        await _agent_engine_with_memory.aclose()

    await close_mq()
    await close_redis()
    await close_db_pool()

    logger.info("应用已关闭")


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
