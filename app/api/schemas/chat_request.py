from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    user_id: str = Field(..., description="用户ID")
    session_id: str = Field(..., description="会话ID")
    message: str = Field(..., description="用户消息")


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="用户ID")
    session_id: str = Field(..., description="会话ID")
    message: str = Field(..., description="用户消息")
