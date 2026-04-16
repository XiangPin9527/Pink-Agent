"""
Analyzer 节点

分析规划：携带全部工具定义 + 长期记忆，制定分步执行策略
"""
from typing import Any, List

from pydantic import BaseModel, Field

from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.schemas import ExecutionPlan, ExecutionStep, StreamEvent
from app.core.orchestrator.prompts import ANALYZER_USER_PROMPT
from app.core.orchestrator.utils import _extract_recent_messages, load_ltm_context
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_RECENT_MESSAGES = 20
MAX_RECENT_MESSAGES_WITHOUT_SUMMARY = 50
MIN_RECENT_MESSAGES = 1


class ExecutionStepOutput(BaseModel):
    step_id: int = Field(description="步骤编号")
    goal: str = Field(description="本步骤的具体目标")
    strategy: str = Field(description="本步骤的执行策略")
    key_considerations: list[str] = Field(default_factory=list, description="注意事项")


class ExecutionPlanOutput(BaseModel):
    overall_goal: str = Field(description="用户的最终目标")
    reasoning: str = Field(description="分析推理过程")
    steps: list[ExecutionStepOutput] = Field(description="执行步骤列表")
    tool_hints: list[str] = Field(default_factory=list, description="可能需要的工具类型")


async def _get_tool_schemas() -> List[dict[str, str]]:
    from app.tools.mcp import get_mcp_manager
    try:
        mcp_manager = get_mcp_manager()
        tools = await mcp_manager.get_tools()
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


def _build_execution_plan(parsed: ExecutionPlanOutput) -> ExecutionPlan:
    steps = [
        ExecutionStep(
            step_id=s.step_id,
            goal=s.goal,
            strategy=s.strategy,
            key_considerations=s.key_considerations,
        )
        for s in parsed.steps
    ]
    steps.sort(key=lambda s: s.step_id)
    return ExecutionPlan(
        overall_goal=parsed.overall_goal,
        reasoning=parsed.reasoning,
        steps=steps,
        tool_hints=parsed.tool_hints,
    )


async def analyzer(state: OrchestratorState) -> OrchestratorState:
    from app.core.llm.service import get_llm_service
    from app.core.orchestrator.memory import get_memory_loader
    from app.core.memory.shortmem import get_short_term_summary, get_msg_count

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

    memory_loader = get_memory_loader()
    ltm_context = await load_ltm_context(memory_loader, user_id, message)
    if ltm_context:
        logger.info("Analyzer 长期记忆加载完成", ltm_context=ltm_context)

    stm_summary = await get_short_term_summary(session_id)

    tool_schemas = await _get_tool_schemas()
    tool_schemas_text = "\n".join(
        f"- {t['name']}: {t['description']}" for t in tool_schemas
    )

    system_prompt = f"""你是一个任务分析规划专家。你的任务是对用户请求进行深度分析，制定执行策略。

请分析用户请求，确定：
1. 用户的最终目标是什么
2. 需要分几个阶段/步骤来完成
3. 每个步骤的子目标和执行策略
4. 可用的工具提示（不需要指定具体工具名称，只需说明需要的工具类型）

你拥有以下工具可用：
{tool_schemas_text}
"""
    system_prompt += ltm_context

    if stm_summary:
        system_prompt += f"\n\n【之前对话的简短摘要】:\n{stm_summary}\n"

    from app.core.memory.user_instruction import get_user_instruction_service
    user_instruction_service = get_user_instruction_service()
    user_instruction = await user_instruction_service.get(user_id)
    if user_instruction:
        user_instruction_text = user_instruction_service.format_for_system_prompt(user_instruction)
        if user_instruction_text:
            system_prompt += f"\n{user_instruction_text}\n"

    msg_count = await get_msg_count(session_id)
    if stm_summary:
        # 有摘要时优先使用 Redis 计数器；计数器异常时回退到默认窗口。
        recent_window = msg_count if msg_count > 0 else MAX_RECENT_MESSAGES
    else:
        # 无摘要时用 state 中真实消息长度估算窗口，避免上下文突然变空。
        recent_window = min(
            max(len(messages) - 1, MIN_RECENT_MESSAGES),
            MAX_RECENT_MESSAGES_WITHOUT_SUMMARY,
        )

    recent_history = _extract_recent_messages(messages, recent_window)
    if recent_history:
        history_context = "\n\n最近对话历史：\n" + "\n".join(
            f"[{msg.__class__.__name__}]: {msg.content[:200]}" +
            ("...(truncated)" if len(msg.content) > 200 else "")
            for msg in recent_history
        )
        system_prompt += history_context

    user_prompt = ANALYZER_USER_PROMPT.format(user_message=message)

    llm = get_llm_service().get_model()
    structured_llm = llm.with_structured_output(ExecutionPlanOutput)

    try:
        response = await structured_llm.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])

        logger.info("Analyzer LLM 响应", session_id=session_id, response=response)

        plan = _build_execution_plan(response)
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
