import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.core.agent.engine import create_orchestrator_engine
from app.core.memory.longterm.store import get_longterm_store
from app.core.memory.mq.service import get_mq_service_instance, close_mq_service
from app.core.rag.retrieval_store import get_retrieval_store
from app.infrastructure.db_client import get_db_pool, close_db_pool
from app.infrastructure.mq_client import (
    get_mq_connection,
    get_mq_channel,
    get_mq_exchange,
    close_mq,
)
from app.infrastructure.redis_client import get_redis, close_redis
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AppResources:
    initialized: bool = False
    redis_ready: bool = False
    db_ready: bool = False
    mq_ready: bool = False
    longterm_store_ready: bool = False
    rag_store_ready: bool = False
    orchestrator_graph: Any | None = None
    mq_service: Any | None = None
    longterm_store: Any | None = None
    rag_store: Any | None = None
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def init_all(self) -> None:
        async with self._lifecycle_lock:
            if self.initialized:
                return

            logger.info("开始初始化应用资源")

            init_errors: list[str] = []

            try:
                await get_redis()
                self.redis_ready = True
            except Exception as e:
                self.redis_ready = False
                init_errors.append(f"redis: {e}")
                logger.warning("Redis 初始化失败", error=str(e))

            try:
                await get_db_pool()
                self.db_ready = True
            except Exception as e:
                self.db_ready = False
                init_errors.append(f"db: {e}")
                logger.warning("DB 初始化失败", error=str(e))

            try:
                await get_mq_connection()
                await get_mq_channel()
                await get_mq_exchange()
                self.mq_ready = True
            except Exception as e:
                self.mq_ready = False
                init_errors.append(f"mq: {e}")
                logger.warning("MQ 初始化失败", error=str(e))

            if self.mq_ready:
                self.mq_service = await get_mq_service_instance()
            else:
                self.mq_service = None

            try:
                self.longterm_store = await get_longterm_store()
                self.longterm_store_ready = True
            except Exception as e:
                self.longterm_store_ready = False
                self.longterm_store = None
                init_errors.append(f"longterm_store: {e}")
                logger.warning("长期记忆 Store 初始化失败", error=str(e))

            try:
                self.rag_store = get_retrieval_store()
                await self.rag_store.ensure_store()
                self.rag_store_ready = True
            except Exception as e:
                self.rag_store_ready = False
                self.rag_store = None
                init_errors.append(f"rag_store: {e}")
                logger.warning("RAG Store 初始化失败", error=str(e))

            if self.longterm_store_ready:
                try:
                    self.orchestrator_graph = await create_orchestrator_engine(
                        store=self.longterm_store,
                        mq_service=self.mq_service,
                    )
                except Exception as e:
                    self.orchestrator_graph = None
                    init_errors.append(f"orchestrator: {e}")
                    logger.warning("Orchestrator 初始化失败", error=str(e))
            else:
                self.orchestrator_graph = None
                init_errors.append("orchestrator: missing longterm store")

            self.initialized = self.orchestrator_graph is not None
            if init_errors:
                logger.warning("应用资源初始化存在失败项", errors=init_errors)
            else:
                logger.info("应用资源初始化完成")

    async def close_all(self) -> None:
        async with self._lifecycle_lock:
            if not self.initialized:
                return

            logger.info("开始释放应用资源")

            if self.orchestrator_graph is not None and hasattr(self.orchestrator_graph, "aclose"):
                await self.orchestrator_graph.aclose()
                self.orchestrator_graph = None

            if self.rag_store is not None and hasattr(self.rag_store, "aclose"):
                await self.rag_store.aclose()
                self.rag_store = None

            from app.core.memory.longterm.store import close_longterm_store

            await close_longterm_store()
            self.longterm_store = None

            await close_mq_service()
            await close_mq()
            await close_redis()
            await close_db_pool()

            self.mq_service = None
            self.redis_ready = False
            self.db_ready = False
            self.mq_ready = False
            self.longterm_store_ready = False
            self.rag_store_ready = False
            self.initialized = False
            logger.info("应用资源释放完成")

    def health_snapshot(self) -> dict[str, str]:
        return {
            "initialized": "up" if self.initialized else "down",
            "redis": "up" if self.redis_ready else "down",
            "db": "up" if self.db_ready else "down",
            "mq": "up" if self.mq_ready else "down",
            "orchestrator": "up" if self.orchestrator_graph is not None else "down",
            "mq_service": "up" if self.mq_service is not None else "down",
            "longterm_store": "up" if self.longterm_store_ready else "down",
            "rag_store": "up" if self.rag_store_ready else "down",
        }


_resources: AppResources | None = None
_resources_lock = asyncio.Lock()


async def get_app_resources() -> AppResources:
    global _resources
    if _resources is None:
        async with _resources_lock:
            if _resources is None:
                _resources = AppResources()
    return _resources


__all__ = ["AppResources", "get_app_resources"]

