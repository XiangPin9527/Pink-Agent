"""
Agent 状态定义

ReAct Agent 使用 langgraph 内置的 MessagesState，
此模块保留扩展状态定义以支持业务元数据传递
"""
from typing import Annotated, Any, Dict, List, Optional

from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """
    Agent 扩展状态

    在 MessagesState 基础上增加业务元数据字段，
    用于追踪、记忆注入和后处理
    """
    messages: Annotated[List[BaseMessage], add_messages]
    user_id: str
    session_id: str


__all__ = ["AgentState"]
