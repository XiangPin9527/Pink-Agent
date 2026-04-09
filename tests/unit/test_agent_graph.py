"""
测试 Agent ReAct 图
"""
import pytest

from app.core.agent.graph import build_react_agent
from app.core.agent.graph.state import AgentState
from app.core.llm import get_llm_service


@pytest.mark.asyncio
async def test_react_agent_structure():
    """测试 ReAct Agent 构建结构"""
    llm_service = get_llm_service()
    model = llm_service.get_model(llm_service.settings.agent_model_name)

    agent = build_react_agent(model=model)

    assert agent is not None


@pytest.mark.asyncio
async def test_react_agent_with_prompt():
    """测试带自定义 prompt 的 ReAct Agent"""
    llm_service = get_llm_service()
    model = llm_service.get_model(llm_service.settings.agent_model_name)

    agent = build_react_agent(
        model=model,
        prompt="你是一个测试助手",
    )

    assert agent is not None
