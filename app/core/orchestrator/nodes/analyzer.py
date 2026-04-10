"""
Analyzer 节点

分析规划：携带全部工具定义 + 长期记忆，制定分步执行策略
"""
import json
import re
from typing import Any, Dict, List

from langchain_core.messages import BaseMessage

from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.schemas import ExecutionPlan, ExecutionStep, StreamEvent
from app.core.orchestrator.prompts import ANALYZER_SYSTEM_PROMPT, ANALYZER_USER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_RECENT_MESSAGES = 20


def _get_tool_schemas() -> List[Dict[str, str]]:
    from app.tools import registry
    try:
        tools = registry.get_all_tools()
        schemas = []
        for tool in tools:
            schemas.append({
                "name": tool.name,
                "description": tool.description,
            })
        return schemas
    except Exception as e:
        logger.warning("获取工具列表失败，使用空列表", error=str(e))
        return []


def _extract_recent_messages(messages: List[BaseMessage], max_count: int = MAX_RECENT_MESSAGES) -> List[BaseMessage]:
    if len(messages) <= 1:
        return []
    return messages[-(max_count + 1):-1]


def _parse_json_response(content: str) -> Dict[str, Any]:
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _build_execution_plan(parsed: Dict[str, Any]) -> ExecutionPlan:
    steps = []
    overall_goal = parsed.get("overall_goal", "")
    reasoning = parsed.get("reasoning", "")
    tool_hints = parsed.get("tool_hints", [])

    for step_data in parsed.get("steps", []):
        try:
            step = ExecutionStep(
                step_id=step_data.get("step_id", 0),
                goal=step_data.get("goal", ""),
                strategy=step_data.get("strategy", ""),
                key_considerations=step_data.get("key_considerations", []),
            )
            steps.append(step)
        except Exception as e:
            logger.warning("解析步骤失败", step_data=step_data, error=str(e))

    steps.sort(key=lambda s: s.step_id)
    return ExecutionPlan(
        overall_goal=overall_goal,
        reasoning=reasoning,
        steps=steps,
        tool_hints=tool_hints,
    )


async def analyzer(state: OrchestratorState) -> OrchestratorState:
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.core.llm.service import get_llm_service
    from app.core.orchestrator.memory import get_memory_loader
    from app.core.memory.shortmem import (
        get_short_term_summary,
    )

    session_id = state["session_id"]
    user_id = state["user_id"]
    messages = state.get("messages", [])
    message = messages[-1].content if messages else ""

    logger.info("Analyzer 开始分析", session_id=session_id, message=message[:100], msg_count=len(messages))

    state["stream_event"] = StreamEvent(
        type="plan_start",
        node="analyzer",
        data={"message": message[:100]}
    )

    ltm_context = ""
    memory_loader = get_memory_loader()
    if memory_loader and user_id and message:
        try:
            raw_ltm = await memory_loader.load_long_term_memory(user_id, message)
            ltm_strings = [
                item["value"].get("content", str(item["value"]))
                for item in raw_ltm
                if item.get("value")
            ]
            if ltm_strings:
                ltm_context = "\n\n已知用户背景信息：\n" + "\n".join(
                    f"- {item}" for item in ltm_strings
                )
                logger.info("Analyzer 长期记忆加载完成", ltm_strings=ltm_strings)
        except Exception as e:
            logger.warning("Analyzer 长期记忆加载失败", error=str(e))

    stm_summary = await get_short_term_summary(session_id)

    tool_schemas = _get_tool_schemas()
    tool_schemas_text = "\n".join(
        f"- {t['name']}: {t['description']}" for t in tool_schemas
    )

    system_prompt = ANALYZER_SYSTEM_PROMPT.format(tool_schemas=tool_schemas_text)
    system_prompt += ltm_context

    if stm_summary:
        system_prompt += f"\n\n【之前对话的简短摘要】:\n{stm_summary}\n"

    recent_history = _extract_recent_messages(messages, MAX_RECENT_MESSAGES)
    if recent_history:
        history_context = "\n\n最近对话历史：\n" + "\n".join(
            f"[{msg.__class__.__name__}]: {msg.content[:200]}" +
            ("...(truncated)" if len(msg.content) > 200 else "")
            for msg in recent_history
        )
        system_prompt += history_context

    user_prompt = ANALYZER_USER_PROMPT.format(user_message=message)

    llm = get_llm_service().get_model()

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        content = response.content
        logger.info("Analyzer LLM 响应", session_id=session_id, content=content)

        parsed = _parse_json_response(content)
        plan = _build_execution_plan(parsed)

        state["execution_plan"] = plan
        state["current_step_index"] = 0

        state["stream_event"] = StreamEvent(
            type="plan_complete",
            node="analyzer",
            data={
                "overall_goal": plan.overall_goal,
                "step_count": len(plan.steps),
                "reasoning": plan.reasoning[:200] if plan.reasoning else "",
                "steps": [
                    {
                        "step_id": s.step_id,
                        "goal": s.goal,
                        "strategy": s.strategy,
                    }
                    for s in plan.steps
                ],
                "tool_hints": plan.tool_hints,
            }
        )

        logger.info(
            "Analyzer 规划完成",
            session_id=session_id,
            overall_goal=plan.overall_goal[:100],
            step_count=len(plan.steps),
            reasoning=plan.reasoning[:100],
        )

    except Exception as e:
        logger.error("Analyzer 执行失败", session_id=session_id, error=str(e))
        state["execution_plan"] = ExecutionPlan(
            overall_goal="",
            reasoning=f"分析失败: {str(e)}",
            steps=[],
            tool_hints=[],
        )
        state["stream_event"] = StreamEvent(
            type="plan_error",
            node="analyzer",
            data={"error": str(e)}
        )

    return state


__all__ = ["analyzer"]