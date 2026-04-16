"""
Simple Handler 节点

处理简单任务：复用 create_agent 逻辑，带完整记忆系统

短期记忆压缩策略:
- 消息 < 10 条: 全量携带，不压缩
- 消息 >= 10 条: 触发异步压缩，MQ Worker 生成摘要
- 后续携带: [摘要] + [最新消息]
"""
from typing import List

from langchain_core.messages import BaseMessage

from app.core.orchestrator.state import OrchestratorState
from app.core.orchestrator.schemas import StreamEvent
from app.core.orchestrator.utils import _extract_recent_messages
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def simple_handler(state: OrchestratorState) -> OrchestratorState:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from app.core.orchestrator.memory import get_memory_loader
    from app.core.orchestrator.simple_agent import build_react_agent
    from app.core.llm.service import get_llm_service
    from app.core.memory.shortmem import (
        get_short_term_summary,
        get_msg_count,
        increment_and_check_compress,
        init_msg_count_if_needed,
        COMPRESS_THRESHOLD,
    )

    session_id = state["session_id"]
    user_id = state["user_id"]
    messages = state.get("messages", [])
    message = messages[-1].content if messages else ""

    stm_summary = await get_short_term_summary(session_id)
    has_summary = bool(stm_summary)

    await init_msg_count_if_needed(session_id, has_summary)

    current_count = await get_msg_count(session_id)
    logger.info("SimpleHandler 开始处理", session_id=session_id, user_id=user_id, msg_count=len(messages), counter=current_count)

    state["stream_event"] = StreamEvent(
        type="simple_start",
        node="simple_handler",
        data={"message": message[:100]}
    )

    memory_loader = get_memory_loader()

    ltm_strings = []
    if memory_loader and user_id and message:
        try:
            raw_ltm = await memory_loader.load_long_term_memory(user_id, message)
            ltm_strings = [
                item["value"].get("content", str(item["value"]))
                for item in raw_ltm
                if item.get("value")
            ]
            logger.info("SimpleHandler 长期记忆加载完成", ltm_strings=ltm_strings)
        except Exception as e:
            logger.warning("SimpleHandler 长期记忆加载失败", error=str(e))

    input_messages = []
    if ltm_strings:
        ltm_context = "已知关于该用户的背景信息：\n" + "\n".join(
            f"- {item}" for item in ltm_strings
        )
        input_messages.append(SystemMessage(content=ltm_context, id="memory_context"))

    if stm_summary:
        stm_context = f"【之前对话的简短摘要】:\n{stm_summary}\n"
        input_messages.append(SystemMessage(content=stm_context, id="shortmem_context"))

    from app.core.memory.user_instruction import get_user_instruction_service
    user_instruction_service = get_user_instruction_service()
    user_instruction = await user_instruction_service.get(user_id)
    if user_instruction:
        user_instruction_text = user_instruction_service.format_for_system_prompt(user_instruction)
        if user_instruction_text:
            input_messages.append(SystemMessage(content=user_instruction_text, id="user_instruction"))

    if current_count == 0:
        max_to_load = COMPRESS_THRESHOLD
    else:
        max_to_load = current_count
    recent_history = _extract_recent_messages(messages, max_to_load)
    if recent_history:
        input_messages.extend(recent_history)

    input_messages.append(HumanMessage(content=message))

    config = {"configurable": {"thread_id": session_id}}

    llm = get_llm_service().get_model()

    from app.tools.mcp import get_mcp_manager
    tools = []
    try:
        mcp_manager = get_mcp_manager()
        tools = await mcp_manager.get_tools()
    except Exception as e:
        logger.warning("SimpleHandler 获取工具列表失败", error=str(e))

    agent = build_react_agent(
        model=llm,
        tools=tools,
    )

    stream_buffer = []
    total_tokens = 0

    try:
        async for event in agent.astream(
            {"messages": input_messages},
            config=config,
            stream_mode="messages"
        ):
            if isinstance(event[0], AIMessage) and event[0].content:
                stream_buffer.append(event[0].content)
    except Exception as e:
        logger.error("SimpleHandler Agent 执行失败", session_id=session_id, error=str(e))
        stream_buffer.append(f"执行失败: {str(e)}")

    final_content = "".join(stream_buffer)
    state["messages"].append(AIMessage(content=final_content))
    state["stream_buffer"] = stream_buffer

    all_messages_for_compress = list(messages) + [AIMessage(content=final_content)]
    await increment_and_check_compress(session_id, all_messages_for_compress, stm_summary)

    from app.core.orchestrator.utils import trigger_longterm_extract
    await trigger_longterm_extract(user_id, session_id, state["messages"])

    state["stream_event"] = StreamEvent(
        type="done",
        node="simple_handler",
        data={
            "total_tokens": total_tokens,
            "content_preview": final_content[:200] if final_content else "",
        }
    )

    logger.info(
        "SimpleHandler 处理完成",
        session_id=session_id,
        response_len=len(final_content),
    )

    return state


__all__ = ["simple_handler"]
