from typing import Optional

from app.core.llm.service import get_llm_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Embedder:
    def __init__(self):
        self._llm_service = None

    async def _ensure_service(self):
        if self._llm_service is None:
            self._llm_service = get_llm_service()

    async def embed_texts(self, texts: list[str]) -> list[Optional[list[float]]]:
        if not texts:
            return []
        await self._ensure_service()
        try:
            embeddings = await self._llm_service.embed_documents(texts)
            logger.debug("文本嵌入完成", count=len(texts))
            return embeddings
        except Exception as e:
            logger.error("文本嵌入失败", count=len(texts), error=str(e))
            return [None for _ in texts]

    async def embed_query(self, text: str) -> Optional[list[float]]:
        await self._ensure_service()
        try:
            embedding = await self._llm_service.embed_query(text)
            logger.debug("查询嵌入完成")
            return embedding
        except Exception as e:
            logger.error("查询嵌入失败", error=str(e))
            return None


_embedder: Optional[Embedder] = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


__all__ = ["Embedder", "get_embedder"]
