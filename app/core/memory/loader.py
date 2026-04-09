from typing import Any

from langgraph.store.base import BaseStore

from app.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryLoader:
    """
    长期记忆加载器

    对话历史由 checkpointer + SummarizationMiddleware 自动管理，
    此类只负责长期记忆的向量语义搜索。
    """

    def __init__(
        self,
        store: BaseStore | None = None,
    ):
        self._store = store

    async def load_long_term_memory(
        self, user_id: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        if not self._store:
            return []

        logger.info(
            "长期记忆开始加载",
            user_id=user_id,
            query=query,
        )
        try:
            namespace = ("users", user_id)
            results = await self._store.asearch(
                namespace, query=query, limit=limit
            )

            memories = []
            for item in results:
                memories.append(
                    {
                        "key": item.key,
                        "value": item.value,
                        "score": getattr(item, "score", None),
                    }
                )

            logger.info(
                "长期记忆加载完成",
                user_id=user_id,
                count=len(memories),
                memories=memories,
                query_len=len(query),
            )
            return memories
        except Exception as e:
            logger.error("长期记忆加载失败", user_id=user_id, error=str(e))
            return []


__all__ = ["MemoryLoader"]
