from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatStreamEvent(BaseModel):
    type: str = Field(..., description="事件类型")
    step: Optional[int] = Field(default=None, description="当前步骤")
    name: Optional[str] = Field(default=None, description="节点名称")
    text: Optional[str] = Field(default=None, description="文本内容")
    result: Optional[str] = Field(default=None, description="执行结果")
    summary: Optional[str] = Field(default=None, description="总结")
    total_tokens: Optional[int] = Field(default=None, description="本轮对话总Token数")
    prompt_tokens: Optional[int] = Field(default=None, description="本轮对话提示Token数")
    completion_tokens: Optional[int] = Field(default=None, description="本轮对话补全Token数")


class TraceMetricEvent(BaseModel):
    trace_id: str
    user_id: str
    session_id: str
    step_name: str
    client_id: Optional[str] = None
    round: int
    model_name: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    status: str = "SUCCESS"
    created_at: Optional[datetime] = None


class ChatResponse(BaseModel):
    trace_id: str = Field(..., description="追踪ID")
    session_id: str = Field(..., description="会话ID")
    user_id: str = Field(..., description="用户ID")
    content: str = Field(..., description="回复内容")
    is_completed: bool = Field(..., description="是否完成")
    total_steps: int = Field(default=0, description="总执行步数")
    total_tokens: int = Field(default=0, description="总Token数")
    trace_metrics: List[TraceMetricEvent] = Field(
        default_factory=list, description="追踪指标"
    )
