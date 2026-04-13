import json
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_orchestrator_engine_dep, get_settings_dep
from app.api.schemas.chat_request import ChatRequest, ChatStreamRequest
from app.api.schemas.chat_response import ChatResponse, ChatStreamEvent
from app.api.schemas.audit_request import AuditRequest, AuditStreamRequest, AuditResponse
from app.config.settings import Settings

router = APIRouter()


@router.post("/chat/stream")
async def chat_stream(
    request: ChatStreamRequest,
    graph: Any = Depends(get_orchestrator_engine_dep),
    settings: Settings = Depends(get_settings_dep),
):
    """
    流式对话接口 (SSE)

    使用 OrchestratorGraph：自动路由简单/复杂任务
    """

    async def event_generator() -> AsyncGenerator[dict, None]:
        config = {"configurable": {"thread_id": request.session_id}}

        try:
            initial_state = {
                "messages": [HumanMessage(content=request.message)],
                "user_id": request.user_id,
                "session_id": request.session_id,
                "task_complexity": "",
                "execution_plan": None,
                "current_step_index": 0,
                "iteration_count": 0,
                "max_iterations": 3,
                "judge_result": None,
                "stream_buffer": [],
                "stream_event": None,
                "audit_files": [],
                "audit_project_name": "",
                "rag_context": "",
                "retrieval_results": [],
                "vulnerabilities": [],
            }

            async for msg_chunk, metadata in graph.astream(
                initial_state,
                config=config,
                stream_mode="messages"
            ):
                if hasattr(msg_chunk, 'content') and msg_chunk.content:
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "content",
                            "text": msg_chunk.content,
                        }, ensure_ascii=False),
                    }

            yield {
                "event": "message",
                "data": json.dumps({"type": "done"}, ensure_ascii=False)
            }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": str(e)}),
            }

    return EventSourceResponse(event_generator())


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    graph: Any = Depends(get_orchestrator_engine_dep),
    settings: Settings = Depends(get_settings_dep),
):
    """
    非流式对话接口

    使用 OrchestratorGraph，自动路由简单/复杂任务
    """
    config = {"configurable": {"thread_id": request.session_id}}

    initial_state = {
        "messages": [HumanMessage(content=request.message)],
        "user_id": request.user_id,
        "session_id": request.session_id,
        "task_complexity": "",
        "execution_plan": None,
        "current_step_index": 0,
        "iteration_count": 0,
        "max_iterations": 3,
        "judge_result": None,
        "stream_buffer": [],
        "stream_event": None,
        "audit_files": [],
        "audit_project_name": "",
        "rag_context": "",
        "retrieval_results": [],
        "vulnerabilities": [],
    }

    try:
        result = await graph.ainvoke(initial_state, config=config)

        final_content = ""
        from langchain_core.messages import AIMessage
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content:
                final_content = msg.content
                break

        return ChatResponse(
            trace_id=request.session_id,
            session_id=request.session_id,
            user_id=request.user_id,
            content=final_content,
            is_completed=True,
            total_steps=result.get("iteration_count", 0),
            total_tokens=0,
            trace_metrics=[],
        )
    except Exception as e:
        return ChatResponse(
            trace_id=request.session_id,
            session_id=request.session_id,
            user_id=request.user_id,
            content=f"执行失败: {str(e)}",
            is_completed=False,
            total_steps=0,
            total_tokens=0,
            trace_metrics=[],
        )


def _build_audit_initial_state(request: AuditRequest | AuditStreamRequest) -> dict:
    audit_files = []
    for f in request.files:
        audit_files.append({
            "file_path": f.file_path,
            "content": f.content,
            "language": f.language,
            "diff": f.diff,
        })

    return {
        "messages": [HumanMessage(content=f"请对以下代码进行安全审计: {', '.join(f.file_path for f in request.files)}")],
        "user_id": request.user_id,
        "session_id": request.session_id,
        "task_complexity": "code_audit",
        "execution_plan": None,
        "current_step_index": 0,
        "iteration_count": 0,
        "max_iterations": 3,
        "judge_result": None,
        "stream_buffer": [],
        "stream_event": None,
        "audit_files": audit_files,
        "audit_project_name": request.project_name,
        "rag_context": "",
        "retrieval_results": [],
        "vulnerabilities": [],
    }


@router.post("/audit/stream")
async def audit_stream(
    request: AuditStreamRequest,
    graph: Any = Depends(get_orchestrator_engine_dep),
    settings: Settings = Depends(get_settings_dep),
):
    async def event_generator() -> AsyncGenerator[dict, None]:
        config = {"configurable": {"thread_id": request.session_id}}

        try:
            initial_state = _build_audit_initial_state(request)

            async for msg_chunk, metadata in graph.astream(
                initial_state,
                config=config,
                stream_mode="messages"
            ):
                if hasattr(msg_chunk, 'content') and msg_chunk.content:
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "content",
                            "text": msg_chunk.content,
                        }, ensure_ascii=False),
                    }

            yield {
                "event": "message",
                "data": json.dumps({"type": "done"}, ensure_ascii=False)
            }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": str(e)}),
            }

    return EventSourceResponse(event_generator())


@router.post("/audit", response_model=AuditResponse)
async def audit(
    request: AuditRequest,
    graph: Any = Depends(get_orchestrator_engine_dep),
    settings: Settings = Depends(get_settings_dep),
):
    config = {"configurable": {"thread_id": request.session_id}}

    initial_state = _build_audit_initial_state(request)

    try:
        result = await graph.ainvoke(initial_state, config=config)

        final_content = ""
        from langchain_core.messages import AIMessage
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content:
                final_content = msg.content
                break

        vulnerabilities = result.get("vulnerabilities", [])

        return AuditResponse(
            trace_id=request.session_id,
            session_id=request.session_id,
            user_id=request.user_id,
            content=final_content,
            is_completed=True,
            vuln_count=len(vulnerabilities),
            vulnerabilities=vulnerabilities,
        )
    except Exception as e:
        return AuditResponse(
            trace_id=request.session_id,
            session_id=request.session_id,
            user_id=request.user_id,
            content=f"审计失败: {str(e)}",
            is_completed=False,
        )