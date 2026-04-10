"""
Orchestrator 状态定义

基于 LangGraph MessagesState，扩展复杂任务所需的业务字段
"""
from typing import Annotated, List, Optional
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict
from app.core.orchestrator.schemas import ExecutionPlan, JudgeResult, StreamEvent


class OrchestratorState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    user_id: str
    session_id: str

    task_complexity: str
    execution_plan: Optional[ExecutionPlan]
    current_step_index: int  # 当前步骤索引
    iteration_count: int  # 迭代次数
    max_iterations: int  # 最大迭代次数
    judge_result: Optional[JudgeResult]  # 判断结果
    stream_buffer: List[str]  # 流式数据缓存
    stream_event: Optional[StreamEvent]  # 流式事件


__all__ = ["OrchestratorState"]
