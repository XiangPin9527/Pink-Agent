from typing import Optional

from app.core.rag.schemas import RetrievalResult
from app.core.rag.embedder import get_embedder
from app.core.rag.retrieval_store import get_retrieval_store
from app.core.rag.reranker import get_reranker
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CodeRetriever:
    async def hybrid_search(
        self,
        query: str,
        project_name: Optional[str] = None,
        languages: Optional[list[str]] = None,
        top_k: int = 10,
        rerank_top_k: int = 5,
    ) -> list[RetrievalResult]:
        embedder = get_embedder()
        query_embedding = await embedder.embed_query(query)
        if not query_embedding:
            logger.warning("查询嵌入为空")
            return []

        pg_filter: Optional[dict] = None
        if project_name or languages:
            pg_filter = {}
            if project_name:
                pg_filter["project_name"] = project_name
            if languages:
                pg_filter["language"] = {"$in": languages}

        store = get_retrieval_store()
        candidates = await store.hybrid_search(
            query=query,
            query_embedding=query_embedding,
            k=top_k * 2,
            filter=pg_filter,
        )

        if not candidates:
            return []

        reranker = get_reranker()
        passages = [c.page_content for c in candidates]
        reranked = reranker.rerank(query, passages, top_k=rerank_top_k)

        id_to_doc = {str(i): candidates[i] for i in range(len(candidates))}
        results = []
        for item in reranked:
            doc = id_to_doc.get(str(item["index"]))
            if doc:
                results.append(RetrievalResult(
                    id=doc.id,
                    project_name=doc.metadata.get("project_name", ""),
                    file_path=doc.metadata.get("file_path", ""),
                    language=doc.metadata.get("language", ""),
                    chunk_type=doc.metadata.get("chunk_type", "code"),
                    content=doc.page_content,
                    metadata=doc.metadata,
                    score=item["score"],
                ))
        return results


_code_retriever: Optional[CodeRetriever] = None


def get_code_retriever() -> CodeRetriever:
    global _code_retriever
    if _code_retriever is None:
        _code_retriever = CodeRetriever()
    return _code_retriever


__all__ = ["CodeRetriever", "get_code_retriever"]
