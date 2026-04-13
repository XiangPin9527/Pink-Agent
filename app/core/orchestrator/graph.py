from typing import Literal

from langgraph.graph import StateGraph, END

from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.nodes import (
    router,
    simple_handler,
    analyzer,
    executor,
    judge,
    reporter,
    code_retriever,
    vulnerability_analyzer,
    audit_reporter,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def route_by_complexity(state: OrchestratorState) -> Literal["simple", "complex", "code_audit"]:
    return state["task_complexity"]


def route_judge(state: OrchestratorState) -> Literal["replan", "summarize"]:
    judge_result = state.get("judge_result")
    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get("max_iterations", 3)

    if judge_result is None:
        return "summarize"

    if not judge_result.passed and iteration_count < max_iterations:
        return "replan"

    return "summarize"


def build_orchestrator_graph() -> StateGraph:
    workflow = StateGraph(OrchestratorState)

    workflow.add_node("router", router)
    workflow.add_node("simple_handler", simple_handler)
    workflow.add_node("analyzer", analyzer)
    workflow.add_node("executor", executor)
    workflow.add_node("judge", judge)
    workflow.add_node("reporter", reporter)
    workflow.add_node("code_retriever", code_retriever)
    workflow.add_node("vulnerability_analyzer", vulnerability_analyzer)
    workflow.add_node("audit_reporter", audit_reporter)

    workflow.set_entry_point("router")

    workflow.add_conditional_edges(
        "router",
        route_by_complexity,
        {
            "simple": "simple_handler",
            "complex": "analyzer",
            "code_audit": "code_retriever",
        }
    )

    workflow.add_edge("analyzer", "executor")
    workflow.add_edge("executor", "judge")

    workflow.add_conditional_edges(
        "judge",
        route_judge,
        {
            "replan": "analyzer",
            "summarize": "reporter",
        }
    )

    workflow.add_edge("code_retriever", "vulnerability_analyzer")
    workflow.add_edge("vulnerability_analyzer", "audit_reporter")

    workflow.add_edge("simple_handler", END)
    workflow.add_edge("reporter", END)
    workflow.add_edge("audit_reporter", END)

    logger.info("OrchestratorGraph 构建完成")

    return workflow


__all__ = ["build_orchestrator_graph", "route_by_complexity", "route_judge"]
