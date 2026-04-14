from typing import Optional

from langchain_core.documents import Document

from app.core.rag.schemas import (
    CodeChunk, FileInfo, RepoInfo, RetrievalResult, AuditFile,
)
from app.core.rag.chunker import get_code_chunker
from app.core.rag.git_loader import get_git_repo_loader
from app.core.rag.retriever import get_code_retriever
from app.core.rag.query_rewriter import get_audit_query_rewriter
from app.core.rag.retrieval_store import get_retrieval_store
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RAGEngine:
    async def ingest_repo(
        self,
        repo_url: str,
        project_name: str,
        branch: str = "main",
        target_extensions: list[str] | None = None,
    ) -> RepoInfo:
        logger.info("开始处理仓库", repo_url=repo_url, project_name=project_name)
        loader = get_git_repo_loader()
        repo_info = await loader.clone_repo(
            repo_url=repo_url,
            branch=branch,
            project_name=project_name,
            target_extensions=target_extensions,
        )

        try:
            files = await loader.scan_files_async(
                repo_info.local_path,
                target_extensions=target_extensions,
            )
            await self._ingest_files(files, project_name)
            logger.info(
                "仓库入库完成",
                project_name=project_name,
                file_count=len(files),
            )
        finally:
            await loader.cleanup(repo_info.local_path)

        return repo_info

    async def ingest_files(
        self,
        project_name: str,
        files: list[dict[str, str]],
    ) -> int:
        file_infos = []
        for f in files:
            file_infos.append(FileInfo(
                file_path=f["file_path"],
                content=f["content"],
                language=f.get("language", "unknown"),
                size=len(f["content"]),
            ))
        return await self._ingest_files(file_infos, project_name)

    async def _ingest_files(
        self,
        files: list[FileInfo],
        project_name: str,
    ) -> int:
        logger.info("开始处理文件", project_name=project_name, file_count=len(files))
        chunker = get_code_chunker()
        store = get_retrieval_store()
        await store.ensure_store()

        all_chunks: list[CodeChunk] = []
        for fi in files:
            chunks = chunker.chunk_file(
                file_path=fi.file_path,
                content=fi.content,
                project_name=project_name,
                language=fi.language,
            )
            all_chunks.extend(chunks)

        if not all_chunks:
            logger.warning("没有生成任何代码块", project_name=project_name)
            return 0

        documents = []
        for chunk in all_chunks:
            doc = Document(
                page_content=chunk.content,
                metadata={
                    "project_name": project_name,
                    "file_path": chunk.metadata.get("file_path", ""),
                    "language": chunk.metadata.get("language", "unknown"),
                    "chunk_type": chunk.metadata.get("chunk_type", "code"),
                    "content_hash": chunk.metadata.get("content_hash", ""),
                },
            )
            documents.append(doc)

        await store.add_documents(documents)
        logger.info(
            "文件入库完成",
            project_name=project_name,
            total_chunks=len(all_chunks),
            inserted=len(documents),
        )
        return len(documents)

    async def audit_search(
        self,
        audit_files: list[AuditFile],
        project_name: str = "",
        top_k: int = 10,
        rerank_top_k: int = 5,
    ) -> list[RetrievalResult]:
        rewriter = get_audit_query_rewriter()
        retriever = get_code_retriever()

        all_results: list[RetrievalResult] = []
        seen_ids: set[str] = set()

        for af in audit_files:
            queries = await rewriter.rewrite(af.content, af.language or "unknown")
            for query in queries:
                results = await retriever.hybrid_search(
                    query=query,
                    project_name=project_name or None,
                    languages=[af.language] if af.language else None,
                    top_k=top_k,
                    rerank_top_k=rerank_top_k,
                )
                for r in results:
                    if r.id not in seen_ids:
                        seen_ids.add(r.id)
                        all_results.append(r)

        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results[:rerank_top_k * 3]

    async def delete_project(self, project_name: str) -> int:
        store = get_retrieval_store()
        await store.ensure_store()
        return await store.delete_by_project(project_name)

    async def list_projects(self) -> list[dict]:
        store = get_retrieval_store()
        await store.ensure_store()
        project_names = await store.list_projects()
        results = []
        for name in project_names:
            status = await store.get_project_status(name)
            if status:
                results.append(status)
        return results

    async def get_project_status(self, project_name: str) -> dict | None:
        store = get_retrieval_store()
        await store.ensure_store()
        return await store.get_project_status(project_name)


_rag_engine: Optional[RAGEngine] = None


def get_rag_engine() -> RAGEngine:
    global _rag_engine
    if _rag_engine is None:
        _rag_engine = RAGEngine()
    return _rag_engine


__all__ = ["RAGEngine", "get_rag_engine"]
