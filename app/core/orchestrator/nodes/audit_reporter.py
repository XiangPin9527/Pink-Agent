from langchain_core.messages import AIMessage

from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.schemas import StreamEvent
from app.core.orchestrator.prompts import AUDIT_REPORTER_PROMPT
from app.core.llm.service import get_llm_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def audit_reporter(state: OrchestratorState) -> OrchestratorState:
    session_id = state["session_id"]
    vulnerabilities = state.get("vulnerabilities", [])
    audit_files_raw = state.get("audit_files", [])

    logger.info(
        "AuditReporter 开始生成报告",
        session_id=session_id,
        vuln_count=len(vulnerabilities),
        file_count=len(audit_files_raw),
    )

    vuln_summary = _format_vulnerabilities(vulnerabilities)
    file_summary = _format_audit_files(audit_files_raw)

    prompt = AUDIT_REPORTER_PROMPT.format(
        file_summary=file_summary,
        vuln_count=len(vulnerabilities),
        vuln_summary=vuln_summary,
    )

    try:
        llm_service = get_llm_service()
        llm = llm_service.get_model()

        from langchain_core.messages import HumanMessage, SystemMessage
        response = await llm.ainvoke([
            SystemMessage(content="你是一个专业的代码安全审计报告撰写专家。"),
            HumanMessage(content=prompt),
        ])

        report = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error("生成审计报告失败", session_id=session_id, error=str(e))
        report = _generate_fallback_report(vulnerabilities, audit_files_raw)

    state["messages"].append(AIMessage(content=report))
    state["stream_buffer"] = [report]

    state["stream_event"] = StreamEvent(
        type="audit_report_result",
        node="audit_reporter",
        data={
            "status": "completed",
            "vuln_count": len(vulnerabilities),
            "report_length": len(report),
        },
    )

    logger.info(
        "AuditReporter 报告生成完成",
        session_id=session_id,
        report_length=len(report),
    )

    return state


def _format_vulnerabilities(vulnerabilities: list[dict]) -> str:
    if not vulnerabilities:
        return "未发现安全漏洞。"

    parts = []
    for i, v in enumerate(vulnerabilities, 1):
        parts.append(
            f"{i}. [{v.get('severity', 'unknown').upper()}] "
            f"{v.get('vuln_type', 'unknown')}\n"
            f"   文件: {v.get('file_path', 'N/A')}\n"
            f"   行号: {v.get('line_range', 'N/A')}\n"
            f"   描述: {v.get('description', 'N/A')}\n"
            f"   修复建议: {v.get('fix_suggestion', 'N/A')}\n"
            f"   置信度: {v.get('confidence', 0):.1%}"
        )
    return "\n\n".join(parts)


def _format_audit_files(audit_files: list[dict]) -> str:
    parts = []
    for f in audit_files:
        parts.append(
            f"- {f.get('file_path', 'N/A')} ({f.get('language', 'unknown')})"
        )
    return "\n".join(parts)


def _generate_fallback_report(
    vulnerabilities: list[dict], audit_files: list[dict]
) -> str:
    lines = ["# 代码安全审计报告\n"]
    lines.append(f"## 审计范围\n共审计 {len(audit_files)} 个文件。\n")

    if not vulnerabilities:
        lines.append("## 审计结果\n未发现安全漏洞。\n")
    else:
        lines.append(f"## 审计结果\n共发现 {len(vulnerabilities)} 个潜在漏洞。\n")
        lines.append(_format_vulnerabilities(vulnerabilities))

    return "\n".join(lines)


__all__ = ["audit_reporter"]
