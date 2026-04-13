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
    current_step_index: int
    iteration_count: int
    max_iterations: int
    judge_result: Optional[JudgeResult]
    stream_buffer: List[str]
    stream_event: Optional[StreamEvent]

    audit_files: List[dict]
    audit_project_name: str
    rag_context: str
    retrieval_results: List[dict]
    vulnerabilities: List[dict]


__all__ = ["OrchestratorState"]
