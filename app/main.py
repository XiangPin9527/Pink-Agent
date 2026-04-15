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
from app.infrastructure.resources import get_app_resources
from app.utils.logger import setup_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(level=settings.log_level, format=settings.log_format)
    logger = get_logger(__name__)
    resources = await get_app_resources()

    logger.info("应用启动中...")

    await resources.init_all()
    if resources.initialized:
        logger.info("核心资源初始化完成")
    else:
        logger.warning("核心资源初始化未完全成功，系统将以降级模式运行")

    if resources.mq_ready:
        try:
            await _start_mq_workers()
            logger.info("MQ Workers 启动完成")
        except Exception as e:
            logger.warning("MQ Workers 启动失败，异步任务将不可用", error=str(e))
    else:
        logger.warning("MQ 未就绪，跳过 MQ Workers 启动")

    yield

    logger.info("应用关闭中...")
    await resources.close_all()

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
