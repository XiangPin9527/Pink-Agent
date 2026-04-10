import base64
from typing import Any

from app.infrastructure.db_client import get_db_pool
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def handle_checkpoint_persist(message: dict[str, Any]) -> None:
    action = message.get("action")
    if action != "persist":
        return

    thread_id = message["thread_id"]
    ns = message["ns"]
    checkpoint_id = message["checkpoint_id"]
    parent_checkpoint_id = message.get("parent_checkpoint_id")
    cp_data = base64.b64decode(message["cp_data"])
    meta_data = base64.b64decode(message["meta_data"]) if message.get("meta_data") else None

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
            VALUES ($1, $2, $3, $4, 'msgpack', $5, $6)
            ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id)
            DO UPDATE SET checkpoint = EXCLUDED.checkpoint, metadata = EXCLUDED.metadata,
                          parent_checkpoint_id = EXCLUDED.parent_checkpoint_id
            """,
            thread_id, ns, checkpoint_id, parent_checkpoint_id, cp_data, meta_data,
        )
    logger.debug("Checkpoint 持久化完成", thread_id=thread_id, checkpoint_id=checkpoint_id)


async def handle_checkpoint_writes(message: dict[str, Any]) -> None:
    action = message.get("action")
    if action != "put_write":
        return

    thread_id = message["thread_id"]
    ns = message["ns"]
    checkpoint_id = message["checkpoint_id"]
    task_id = message["task_id"]
    idx = message["idx"]
    channel = message["channel"]
    write_type = message["write_type"]
    write_blob = base64.b64decode(message["write_blob"])

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            DO UPDATE SET blob = EXCLUDED.blob, type = EXCLUDED.type
            """,
            thread_id, ns, checkpoint_id, task_id, idx, channel, write_type, write_blob,
        )
    logger.debug("Checkpoint write 持久化完成", thread_id=thread_id, checkpoint_id=checkpoint_id)


async def handle_longterm_extract(
    longterm_extractor: Any, message: dict[str, Any]
) -> None:
    user_id = message.get("user_id", "")
    thread_id = message.get("thread_id", "")
    msgs = message.get("messages", [])
    total_msg_count = message.get("total_msg_count", 0)
    if user_id and msgs:
        await longterm_extractor.extract_and_store(user_id, thread_id, msgs)
        from app.infrastructure.redis_client import get_redis
        r = await get_redis()
        await r.set(f"ltm_last_extract:{thread_id}", str(total_msg_count))
        logger.debug("长期记忆提取位置已更新", thread_id=thread_id, position=total_msg_count)


async def handle_shortmem_compress(message: dict[str, Any]) -> None:
    """
    处理短期记忆压缩任务

    从 MQ 消息中获取待压缩的消息内容，生成摘要并更新 Redis

    Args:
        message: MQ 消息，包含 session_id, messages, old_summary
    """
    from app.core.memory.shortmem import (
        KEEP_FRESH_MESSAGES,
        set_short_term_summary,
        reset_msg_count_after_compress,
    )

    session_id = message.get("session_id", "")
    messages = message.get("messages", [])
    old_summary = message.get("old_summary", "")

    if not session_id:
        logger.warning("短期记忆压缩任务缺少 session_id")
        return

    if not messages:
        logger.info("无消息需要压缩", session_id=session_id)
        return

    keep_count = KEEP_FRESH_MESSAGES
    if len(messages) <= keep_count:
        logger.info("消息数量少于保留数量，无需压缩", session_id=session_id, msg_count=len(messages))
        return

    to_compress = messages[:-keep_count]
    summary_text = await _generate_summary(to_compress, old_summary, session_id)

    success = await set_short_term_summary(session_id, summary_text)
    if success:
        await reset_msg_count_after_compress(session_id)
        logger.info(
            "短期记忆压缩完成",
            session_id=session_id,
            compressed_count=len(to_compress),
            kept_count=keep_count,
            summary_len=len(summary_text),
        )
    else:
        logger.error("更新短期记忆摘要失败", session_id=session_id)


async def _generate_summary(
    messages: list, old_summary: str, session_id: str
) -> str:
    """
    使用 LLM 生成对话摘要

    Args:
        messages: 待压缩的消息列表
        old_summary: 旧的摘要
        session_id: 会话 ID

    Returns:
        新的摘要文本
    """
    from app.core.llm.service import get_llm_service
    from langchain_core.messages import HumanMessage, AIMessage

    if not messages:
        return old_summary

    message_texts = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "用户"
            content = msg.content
        elif isinstance(msg, AIMessage):
            role = "助手"
            content = msg.content
        elif isinstance(msg, dict):
            role = "用户" if msg.get("type") == "human" else "助手"
            content = msg.get("content", "")
        else:
            role = msg.__class__.__name__
            content = msg.content if hasattr(msg, "content") else str(msg)
        message_texts.append(f"{role}: {content}")

    full_text = "\n".join(message_texts)

    prompt_parts = ["请将以下对话内容压缩成简洁的摘要，保留关键信息、用户意图和重要结论。", ""]

    if old_summary:
        prompt_parts.append(f"【之前的摘要】:\n{old_summary}\n")

    prompt_parts.append("【待压缩的对话】:")
    prompt_parts.append(full_text)
    prompt_parts.append("")
    prompt_parts.append("请生成一段简洁的摘要（不超过200字），涵盖对话的核心内容：")

    prompt = "\n".join(prompt_parts)

    try:
        llm = get_llm_service().get_model()
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        summary = response.content if hasattr(response, "content") else str(response)
        summary = summary.strip()
        logger.debug("摘要生成成功", session_id=session_id, summary_len=len(summary))
        return summary
    except Exception as e:
        logger.error("生成摘要失败", session_id=session_id, error=str(e))
        return old_summary


__all__ = [
    "handle_checkpoint_persist",
    "handle_checkpoint_writes",
    "handle_longterm_extract",
    "handle_shortmem_compress",
]
