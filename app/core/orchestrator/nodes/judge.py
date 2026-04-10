"""
Judge 节点

评估节点：评估执行结果是否通过
"""
import json
import re

from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.schemas import JudgeResult, StreamEvent
from app.core.orchestrator.prompts import JUDGE_SYSTEM_PROMPT, JUDGE_USER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _parse_judge_response(content: str) -> JudgeResult:
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            return JudgeResult(
                passed=parsed.get("passed", False),
                reasons=parsed.get("reasons", []),
                failed_steps=parsed.get("failed_steps", []),
            )
        except json.JSONDecodeError:
            pass

    passed = "passed" in content.lower() and "false" not in content.lower()
    return JudgeResult(passed=passed, reasons=[content], failed_steps=[])


async def judge(state: OrchestratorState) -> OrchestratorState:
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    from app.core.llm.service import get_llm_service

    session_id = state["session_id"]
    plan = state.get("execution_plan")
    messages = state.get("messages", [])
    iteration = state.get("iteration_count", 0)

    logger.info("Judge 开始评估", session_id=session_id, iteration=iteration)

    state["stream_event"] = StreamEvent(
        type="judge_start",
        node="judge",
        data={"iteration": iteration}
    )

    if not plan or not plan.steps:
        judge_result = JudgeResult(
            passed=True,
            reasons=["No execution plan, consider passed"],
            failed_steps=[],
        )
        state["judge_result"] = judge_result
        state["iteration_count"] = iteration + 1
        return state

    overall_goal = plan.overall_goal if plan else ""
    plan_summary = f"目标：{overall_goal}\n\n"
    if plan and plan.steps:
        plan_summary += "执行步骤：\n"
        for s in plan.steps:
            plan_summary += f"  Step {s.step_id}: {s.goal} (策略: {s.strategy})\n"

    execution_logs = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.content.startswith("[Step"):
            execution_logs.append(msg.content)

    actual_results = "\n\n".join(execution_logs) if execution_logs else "No execution results"

    user_prompt = JUDGE_USER_PROMPT.format(
        goal=overall_goal,
        strategy=plan.reasoning if plan else "",
        actual_results=actual_results,
    )

    llm = get_llm_service().get_model()

    try:
        response = await llm.ainvoke([
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])

        content = response.content
        logger.info("Judge LLM 响应", session_id=session_id, content_len=len(content))

        judge_result = _parse_judge_response(content)

    except Exception as e:
        logger.error("Judge 执行失败", session_id=session_id, error=str(e))
        judge_result = JudgeResult(
            passed=False,
            reasons=[f"Judge execution failed: {str(e)}"],
            failed_steps=[],
        )

    state["judge_result"] = judge_result
    state["iteration_count"] = iteration + 1

    state["stream_event"] = StreamEvent(
        type="judge_result",
        node="judge",
        data={
            "passed": judge_result.passed,
            "reasons": judge_result.reasons,
            "failed_steps": judge_result.failed_steps,
            "iteration": iteration + 1,
        }
    )

    logger.info(
        "Judge 评估完成",
        session_id=session_id,
        passed=judge_result.passed,
        iteration=iteration + 1,
        reasons=judge_result.reasons,
    )

    return state


__all__ = ["judge"]