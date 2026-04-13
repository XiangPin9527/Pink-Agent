"""
Judge 节点

评估节点：评估执行结果是否通过
"""
from pydantic import BaseModel, Field

from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.schemas import JudgeResult, StreamEvent
from app.core.orchestrator.prompts import JUDGE_USER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


class JudgeOutput(BaseModel):
    passed: bool = Field(description="执行结果是否通过")
    reasons: list[str] = Field(description="通过或失败的原因列表")
    failed_steps: list[int] = Field(default_factory=list, description="失败的步骤编号列表")


async def judge(state: OrchestratorState) -> OrchestratorState:
    from langchain_core.messages import HumanMessage, AIMessage
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

    system_prompt = """你是一个质量评估专家。请评估执行结果是否达到了用户目标。

评估标准：
1. 完整性：是否完成了用户请求的所有部分？
2. 准确性：结果是否符合用户意图？
3. 质量：结果是否有错误或遗漏？

请严格按照JSON格式输出，包含passed、reasons和failed_steps字段。"""

    user_prompt = f"""执行目标：{overall_goal}
执行策略：{plan.reasoning if plan else ""}

实际执行结果：
{actual_results}

请评估是否通过："""

    llm = get_llm_service().get_model()
    structured_llm = llm.with_structured_output(JudgeOutput)

    try:
        response = await structured_llm.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])

        logger.info("Judge LLM 响应", session_id=session_id, response=response)

        judge_result = JudgeResult(
            passed=response.passed,
            reasons=response.reasons,
            failed_steps=response.failed_steps,
        )

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
