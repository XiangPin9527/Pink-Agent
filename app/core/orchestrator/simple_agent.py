"""
Simple Agent 构建

基于 LangChain create_agent 构建 ReAct 智能体
"""
from typing import Any, Sequence

from langchain_core.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain.agents import create_agent

from app.core.orchestrator.prompts import AGENT_SYSTEM_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


def build_react_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool] | None = None,
    prompt: str | None = None,
    checkpointer: Any = None,
    store: Any = None,
) -> Any:
    """
    构建 ReAct Agent

    Args:
        model: LLM 模型实例
        tools: 工具列表
        prompt: 系统提示词（默认使用 AGENT_SYSTEM_PROMPT）
        checkpointer: 状态持久化器
        store: 长期记忆存储

    Returns:
        编译后的 CompiledStateGraph
    """
    agent = create_agent(
        model=model,
        tools=tools or [],
        system_prompt=prompt or AGENT_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        store=store,
    )

    logger.info(
        "SimpleAgent 构建完成",
        has_tools=bool(tools),
        has_checkpointer=checkpointer is not None,
        has_store=store is not None,
    )

    return agent