import json
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_agent_engine_dep, get_settings_dep
from app.api.schemas.chat_request import ChatRequest, ChatStreamRequest
from app.api.schemas.chat_response import ChatResponse, ChatStreamEvent
from app.config.settings import Settings

router = APIRouter()


@router.post("/chat/stream")
async def chat_stream(
    request: ChatStreamRequest,
    engine: Any = Depends(get_agent_engine_dep),
    settings: Settings = Depends(get_settings_dep),
):
    """
    流式对话接口 (SSE)
    """

    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            async for event in engine.astream_chat(request):
                yield {
                    "event": "message",
                    "data": json.dumps(event.model_dump(), ensure_ascii=False),
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
    engine: Any = Depends(get_agent_engine_dep),
    settings: Settings = Depends(get_settings_dep),
):
    """
    非流式对话接口

    返回完整的对话结果
    """
    result = await engine.chat(request)
    return result
