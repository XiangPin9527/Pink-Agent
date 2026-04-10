import json
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_orchestrator_engine_dep, get_settings_dep
from app.api.schemas.chat_request import ChatRequest, ChatStreamRequest
from app.api.schemas.chat_response import ChatResponse, ChatStreamEvent
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