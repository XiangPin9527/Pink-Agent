from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.schemas import StreamEvent
from app.core.rag.schemas import AuditFile
from app.core.rag.engine import get_rag_engine
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def code_retriever(state: OrchestratorState) -> OrchestratorState:
    session_id = state["session_id"]
    audit_files_raw = state.get("audit_files", [])
    project_name = state.get("audit_project_name", "")

    logger.info(
        "CodeRetriever 开始检索",
        session_id=session_id,
        file_count=len(audit_files_raw),
        project_name=project_name,
    )

    audit_files = []
    for f in audit_files_raw:
        audit_files.append(AuditFile(
            file_path=f.get("file_path", ""),
            content=f.get("content", ""),
            language=f.get("language"),
            diff=f.get("diff"),
        ))

    if not audit_files:
        state["rag_context"] = ""
        state["retrieval_results"] = []
        state["stream_event"] = StreamEvent(
            type="code_retriever_result",
            node="code_retriever",
            data={"status": "no_files", "result_count": 0},
        )
        return state

    try:
        rag_engine = get_rag_engine()
        results = await rag_engine.audit_search(
            audit_files=audit_files,
            project_name=project_name,
            top_k=10,
            rerank_top_k=5,
        )

        context_parts = []
        for r in results:
            context_parts.append(
                f"--- [{r.file_path}] (score: {r.score:.3f}) ---\n{r.content}\n"
            )

        rag_context = "\n".join(context_parts)
        state["rag_context"] = rag_context
        state["retrieval_results"] = [
            {
                "id": r.id,
                "file_path": r.file_path,
                "language": r.language,
                "score": r.score,
                "content": r.content[:200],
            }
            for r in results
        ]

        logger.info(
            "CodeRetriever 检索完成",
            session_id=session_id,
            result_count=len(results),
        )
    except Exception as e:
        logger.error("CodeRetriever 检索失败", session_id=session_id, error=str(e))
        state["rag_context"] = ""
        state["retrieval_results"] = []

    state["stream_event"] = StreamEvent(
        type="code_retriever_result",
        node="code_retriever",
        data={
            "status": "completed",
            "result_count": len(state.get("retrieval_results", [])),
        },
    )

    return state


__all__ = ["code_retriever"]
