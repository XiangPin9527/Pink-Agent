from typing import Optional

from sentence_transformers import CrossEncoder

from app.utils.logger import get_logger

logger = get_logger(__name__)


class Reranker:
    DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        self._model: Optional[CrossEncoder] = None

    def _ensure_model(self):
        if self._model is None:
            self._model = CrossEncoder(self.model_name)
            logger.info("CrossEncoder 模型加载完成", model=self.model_name)

    def rerank(
        self,
        query: str,
        passages: list[str],
        top_k: int = 5,
    ) -> list[dict]:
        self._ensure_model()

        pairs = [[query, passage] for passage in passages]
        scores = self._model.predict(pairs)

        ranked = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True
        )[:top_k]

        return [
            {"index": idx, "score": float(score), "text": passages[idx]}
            for idx, score in ranked
        ]


_reranker: Optional[Reranker] = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker


__all__ = ["Reranker", "get_reranker"]
