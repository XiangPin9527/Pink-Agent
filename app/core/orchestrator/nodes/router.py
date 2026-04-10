"""
Router 节点

复杂度分类：模式匹配 → LLM 兜底
每次根据当前消息内容独立判断复杂度，不使用缓存
"""
import re
from typing import List

from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.schemas import StreamEvent
from app.core.orchestrator.prompts import ROUTER_SYSTEM_PROMPT, ROUTER_USER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)

SIMPLE_PATTERNS: List[str] = [
    r"^(你好|hi|hello|嗨|hi there|您好)",
    r"^(什么是|告诉我|帮我查一下|查一下|请问)",
    r"^(翻译|convert|转换成|换算)",
    r"^(总结|概括|摘要|提取要点)",
    r"^(你好|hi|hello|嗨){1}\s*$",
]

COMPLEX_PATTERNS: List[str] = [
    r"(多个|一系列|整个项目|完整的|所有文件)",
    r"(分析.{0,20}并.{0,20}然后|对比.{0,20}并)",
    r"(代码生成|项目搭建|系统设计|架构设计)",
    r".{200,}",
]


def _match_patterns(message: str, patterns: List[str]) -> bool:
    for p in patterns:
        if re.search(p, message, re.IGNORECASE):
            return True
    return False


async def router(state: OrchestratorState) -> OrchestratorState:
    session_id = state["session_id"]
    message = state["messages"][-1].content if state["messages"] else ""

    logger.info("Router 开始处理", session_id=session_id, message=message[:50])

    complexity = None

    if _match_patterns(message, SIMPLE_PATTERNS):
        complexity = "simple"
        logger.info("Router 模式匹配为 simple", session_id=session_id)
    elif _match_patterns(message, COMPLEX_PATTERNS):
        complexity = "complex"
        logger.info("Router 模式匹配为 complex", session_id=session_id)

    if complexity is None:
        from app.core.llm.service import get_llm_service
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = get_llm_service().get_model()
        user_prompt = ROUTER_USER_PROMPT.format(user_message=message)

        response = await llm.ainvoke([
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt)
        ])

        content = response.content.lower().strip()
        complexity = "simple" if "simple" in content else "complex"
        logger.info("Router LLM 分类结果", session_id=session_id, complexity=complexity)

    if complexity is None:
        complexity = "simple"

    state["task_complexity"] = complexity
    state["stream_event"] = StreamEvent(
        type="router_result",
        node="router",
        data={"complexity": complexity}
    )

    return state


__all__ = ["router"]