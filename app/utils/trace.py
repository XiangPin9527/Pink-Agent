"""
追踪上下文

用于全链路追踪和日志关联
"""
import contextvars
from dataclasses import dataclass
from typing import Optional


_trace_context: contextvars.ContextVar[Optional["TraceContext"]] = contextvars.ContextVar(
    "trace_context", default=None
)


@dataclass
class TraceContext:
    """
    追踪上下文
    
    用于全链路追踪和日志关联
    """
    trace_id: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    client_id: Optional[str] = None
    round: Optional[int] = None


def get_trace_context() -> Optional[TraceContext]:
    """获取当前追踪上下文"""
    return _trace_context.get()


def set_trace_context(context: TraceContext) -> None:
    """设置追踪上下文"""
    _trace_context.set(context)


def clear_trace_context() -> None:
    """清除追踪上下文"""
    _trace_context.set(None)


__all__ = [
    "TraceContext",
    "get_trace_context",
    "set_trace_context",
    "clear_trace_context",
]
