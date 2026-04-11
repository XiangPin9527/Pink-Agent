"""
Reporter 节点

总结节点：整合执行过程，生成面向用户的总结报告，并裁剪消息防爆
"""
from typing import List

from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.schemas import StreamEvent
from app.core.orchestrator.prompts import REPORTER_SYSTEM_PROMPT, REPORTER_USER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def reporter(state: OrchestratorState) -> OrchestratorState:
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
    from app.core.llm.service import get_llm_service

    session_id = state["session_id"]
    plan = state.get("execution_plan")
    judge_result = state.get("judge_result")
    messages = state.get("messages", [])
    iteration = state.get("iteration_count", 0)

    logger.info("Reporter 开始总结", session_id=session_id, iteration=iteration)

    overall_goal = plan.overall_goal if plan else "未知目标"

    plan_summary_parts = [f"执行目标：{overall_goal}\n"]
    if plan and plan.steps:
        plan_summary_parts.append("执行步骤：")
        for s in plan.steps:
            plan_summary_parts.append(f"  Step {s.step_id}: {s.goal} (策略: {s.strategy})")
        if plan.reasoning:
            plan_summary_parts.append(f"\n分析推理：{plan.reasoning}")
    plan_summary = "\n".join(plan_summary_parts)

    execution_logs = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.content.startswith("[Step"):
            execution_logs.append(msg.content)

    execution_log = "\n\n".join(execution_logs) if execution_logs else "无执行记录"

    judge_passed = judge_result.passed if judge_result else False
    judge_reasons = judge_result.reasons if judge_result else []
    judge_summary = f"评估结果：通过={judge_passed}，原因={', '.join(judge_reasons) if judge_reasons else '无'}"

    user_prompt = REPORTER_USER_PROMPT.format(
        goal=overall_goal,
        execution_log=execution_log,
        judge_summary=judge_summary,
    )

    llm = get_llm_service().get_model()

    try:
        response = await llm.ainvoke([
            SystemMessage(content=REPORTER_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])

        final_content = response.content
        logger.info(
            "Reporter 总结完成",
            session_id=session_id,
            content_len=len(final_content),
        )

        final_message = AIMessage(content=final_content)
        state["messages"].append(final_message)

        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        human_msgs = [m for m in messages if not isinstance(m, (AIMessage, SystemMessage))]

        from app.core.orchestrator.utils import trigger_longterm_extract
        user_id = state.get("user_id", "")
        await trigger_longterm_extract(user_id, session_id, messages)

        if human_msgs:
            last_human = human_msgs[-1]
            state["messages"] = system_msgs + [final_message, last_human]
        else:
            state["messages"] = system_msgs + [final_message]

        state["stream_buffer"] = [final_content]
        state["stream_event"] = StreamEvent(
            type="final",
            node="reporter",
            data={
                "content": final_content,
                "iteration_count": iteration,
                "passed": judge_passed,
            }
        )

        logger.info(
            "Reporter 处理完成",
            session_id=session_id,
            final_content_len=len(final_content),
            remaining_messages=len(state["messages"]),
        )

    except Exception as e:
        logger.error("Reporter 执行失败", session_id=session_id, error=str(e))

        error_content = f"总结生成失败: {str(e)}"
        state["messages"].append(AIMessage(content=error_content))
        state["stream_buffer"] = [error_content]
        state["stream_event"] = StreamEvent(
            type="final",
            node="reporter",
            data={
                "content": error_content,
                "iteration_count": iteration,
                "passed": False,
                "error": str(e),
            }
        )

        from app.core.orchestrator.utils import trigger_longterm_extract
        user_id = state.get("user_id", "")
        await trigger_longterm_extract(user_id, session_id, messages)

    return state


__all__ = ["reporter"]