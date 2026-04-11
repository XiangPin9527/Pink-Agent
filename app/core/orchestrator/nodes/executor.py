"""
Executor 节点

使用 create_agent 包装的 ReAct Agent 执行工具任务
"""
from typing import Any, List

from langchain_core.messages import BaseMessage

from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.schemas import StreamEvent
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _extract_recent_messages(messages: List[BaseMessage], max_count: int) -> List[BaseMessage]:
    if len(messages) <= 1:
        return []
    return messages[-(max_count + 1):-1]


EXECUTOR_SYSTEM_PROMPT = """你是一个任务执行专家。你需要根据分析专家的规划，执行具体任务。

分析专家的分析：
{analysis}

当前步骤目标：{goal}

执行策略：{strategy}

注意事项：{considerations}

已知用户背景信息：
{ltm_context}

【之前对话的简短摘要】：
{stm_summary}

最近对话历史：
{recent_history}

你拥有以下工具可用，请根据实际情况调用。
每次只调用一个工具，等待结果后再决定下一步。
当你认为当前步骤目标已经完成时，明确回复"步骤完成"并给出结果摘要。"""


async def executor(state: OrchestratorState) -> OrchestratorState:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain.agents import create_agent
    from app.core.orchestrator.memory import get_memory_loader
    from app.core.memory.shortmem import (
        get_short_term_summary,
        get_msg_count,
        increment_and_check_compress,
        init_msg_count_if_needed,
        COMPRESS_THRESHOLD,
    )

    session_id = state["session_id"]
    user_id = state["user_id"]
    plan = state.get("execution_plan")
    step_idx = state.get("current_step_index", 0)
    messages = state.get("messages", [])

    if not plan or not plan.steps:
        logger.warning("Executor 未找到执行计划", session_id=session_id)
        state["stream_event"] = StreamEvent(
            type="executor_error",
            node="executor",
            data={"error": "no execution plan"}
        )
        return state

    if step_idx >= len(plan.steps):
        logger.info("Executor 所有步骤执行完毕", session_id=session_id, total_steps=len(plan.steps))
        state["stream_event"] = StreamEvent(
            type="all_steps_complete",
            node="executor",
            data={"total_steps": len(plan.steps)}
        )
        return state

    stm_summary = await get_short_term_summary(session_id)
    has_summary = bool(stm_summary)

    await init_msg_count_if_needed(session_id, has_summary)

    current_count = await get_msg_count(session_id)
    logger.info("Executor 开始处理", session_id=session_id, user_id=user_id, msg_count=len(messages), counter=current_count)

    ltm_context = ""
    memory_loader = get_memory_loader()
    if memory_loader and user_id:
        try:
            raw_ltm = await memory_loader.load_long_term_memory(user_id, plan.reasoning or "")
            ltm_strings = [
                item["value"].get("content", str(item["value"]))
                for item in raw_ltm
                if item.get("value")
            ]
            if ltm_strings:
                ltm_context = "\n".join(f"- {item}" for item in ltm_strings)
                logger.info("Executor 长期记忆加载完成", ltm_strings=ltm_strings)
        except Exception as e:
            logger.warning("Executor 长期记忆加载失败", error=str(e))

    recent_history = _extract_recent_messages(messages, current_count if current_count > 0 else COMPRESS_THRESHOLD)
    recent_history_text = ""
    if recent_history:
        recent_history_text = "\n".join(
            f"[{msg.__class__.__name__}]: {msg.content[:200]}" +
            ("...(truncated)" if len(msg.content) > 200 else "")
            for msg in recent_history
        )
    else:
        recent_history_text = "无"

    from app.tools import registry
    tools = []
    try:
        tools = registry.get_all_tools()
    except Exception as e:
        logger.warning("获取工具列表失败", error=str(e))

    execution_records = []

    while step_idx < len(plan.steps):
        step = plan.steps[step_idx]
        considerations = "\n".join(f"- {c}" for c in step.key_considerations) if step.key_considerations else "无"

        logger.info(
            "Executor 执行步骤",
            session_id=session_id,
            step_id=step.step_id,
            goal=step.goal,
            progress=f"{step_idx + 1}/{len(plan.steps)}",
        )

        state["stream_event"] = StreamEvent(
            type="step_start",
            node="executor",
            data={
                "step_id": step.step_id,
                "goal": step.goal,
                "strategy": step.strategy,
                "progress": f"{step_idx + 1}/{len(plan.steps)}",
            }
        )

        system_prompt = EXECUTOR_SYSTEM_PROMPT.format(
            analysis=plan.reasoning or "无",
            goal=step.goal,
            strategy=step.strategy,
            considerations=considerations,
            ltm_context=ltm_context or "无",
            stm_summary=stm_summary or "无",
            recent_history=recent_history_text,
        )

        from app.core.llm.service import get_llm_service

        llm = get_llm_service().get_model()

        agent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=system_prompt,
        )

        step_input = f"请执行步骤 {step.step_id}：{step.goal}"
        step_result = ""

        try:
            result = await agent.ainvoke({"messages": [HumanMessage(content=step_input)]})

            if isinstance(result, dict) and "messages" in result:
                messages = result["messages"]
                for msg in messages:
                    if isinstance(msg, AIMessage):
                        step_result = msg.content
                        break

                all_contents = []
                for msg in messages:
                    if isinstance(msg, AIMessage) and msg.content:
                        all_contents.append(msg.content)

                if all_contents:
                    step_result = "\n".join(all_contents)
            else:
                step_result = str(result)

        except Exception as e:
            logger.error(
                "Executor Agent 执行失败",
                session_id=session_id,
                step_id=step.step_id,
                error=str(e),
            )
            step_result = f"执行失败: {str(e)}"

        state["messages"].append(AIMessage(
            content=f"[Step {step.step_id}] Goal: {step.goal}\nStrategy: {step.strategy}\nResult:\n{step_result}"
        ))

        execution_records.append({
            "step_id": step.step_id,
            "goal": step.goal,
            "strategy": step.strategy,
            "result": step_result,
        })

        state["stream_event"] = StreamEvent(
            type="step_complete",
            node="executor",
            data={
                "step_id": step.step_id,
                "goal": step.goal,
                "result_preview": step_result[:200] if step_result else "",
                "progress": f"{step_idx + 1}/{len(plan.steps)}",
            }
        )

        step_idx += 1
        state["current_step_index"] = step_idx

    logger.info(
        "Executor 执行完成",
        session_id=session_id,
        completed_steps=len(execution_records),
        total_steps=len(plan.steps),
    )

    all_messages_for_compress = list(state.get("messages", []))
    if all_messages_for_compress:
        await increment_and_check_compress(session_id, all_messages_for_compress, stm_summary or "")

    return state


__all__ = ["executor"]
