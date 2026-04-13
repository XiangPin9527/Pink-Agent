from typing import Optional

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RetrievalStore:
    TABLE_NAME = "code_vectors"
    VECTOR_SIZE = 1024

    def __init__(self):
        self._engine = None
        self._store = None

    def _get_connection_string(self) -> str:
        settings = get_settings()
        return settings.database_url.replace("+asyncpg", "")

    def _get_embeddings(self) -> OpenAIEmbeddings:
        settings = get_settings()
        return OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            dimensions=settings.openai_embedding_dims,
            check_embedding_ctx_length=False,
        )

    async def ensure_store(self):
        if self._store is not None:
            return

        from langchain_postgres import PGEngine, PGVectorStore

        self._engine = PGEngine.from_connection_string(self._get_connection_string())

        await self._engine.ainit_vectorstore_table(
            table_name=self.TABLE_NAME,
            vector_size=self.VECTOR_SIZE,
            overwrite=False,
        )

        self._store = await PGVectorStore.create(
            engine=self._engine,
            table_name=self.TABLE_NAME,
            embedding_service=self._get_embeddings(),
            metadata_json_column="cmetadata",
        )

        logger.info("PGVectorStore 初始化完成", table=self.TABLE_NAME)

    async def add_documents(
        self,
        documents: list[Document],
    ) -> None:
        await self.ensure_store()
        await self._store.aadd_documents(documents)
        logger.debug("文档入库完成", count=len(documents))

    async def similarity_search(
        self,
        query_embedding: list[float],
        k: int = 20,
        filter: Optional[dict] = None,
    ) -> list[Document]:
        await self.ensure_store()
        return await self._store.asimilarity_search_by_vector(
            embedding=query_embedding,
            k=k,
            filter=filter,
        )

    async def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        k: int = 20,
        filter: Optional[dict] = None,
    ) -> list[Document]:
        await self.ensure_store()
        return await self._store.asimilarity_search(
            query=query,
            embedding=query_embedding,
            k=k,
            filter=filter,
        )

    async def delete_by_project(self, project_name: str) -> int:
        await self.ensure_store()
        async with self._engine.connect() as conn:
            row = await conn.fetchrow(
                """
                WITH deleted AS (
                    DELETE FROM code_vectors
                    WHERE cmetadata->>'project_name' = $1
                    RETURNING 1
                )
                SELECT COUNT(*) AS deleted_count FROM deleted
                """,
                project_name,
            )
            return row["deleted_count"] if row else 0

    async def list_projects(self) -> list[str]:
        await self.ensure_store()
        async with self._engine.connect() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT cmetadata->>'project_name' AS project_name
                FROM code_vectors
                WHERE cmetadata->>'project_name' IS NOT NULL
                ORDER BY project_name
                """
            )
            return [row["project_name"] for row in rows]

    async def get_project_status(self, project_name: str) -> Optional[dict]:
        await self.ensure_store()
        async with self._engine.connect() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    cmetadata->>'project_name' AS project_name,
                    COUNT(*) AS chunk_count,
                    COUNT(DISTINCT cmetadata->>'file_path') AS file_count,
                    COUNT(DISTINCT cmetadata->>'language') AS language_count
                FROM code_vectors
                WHERE cmetadata->>'project_name' = $1
                GROUP BY cmetadata->>'project_name'
                """,
                project_name,
            )
            if row is None:
                return None
            return {
                "project_name": row["project_name"],
                "chunk_count": row["chunk_count"],
                "file_count": row["file_count"],
                "language_count": row["language_count"],
            }


_retrieval_store: Optional[RetrievalStore] = None


def get_retrieval_store() -> RetrievalStore:
    global _retrieval_store
    if _retrieval_store is None:
        _retrieval_store = RetrievalStore()
    return _retrieval_store


__all__ = ["RetrievalStore", "get_retrieval_store"]
