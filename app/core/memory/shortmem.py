"""
短期记忆压缩模块

提供基于 Redis 的异步摘要压缩功能，用于管理对话短期记忆。
当未压缩消息达到阈值时，触发 MQ 异步压缩，生成对话摘要。

工作原理:
1. 消息计数器存储在 Redis: {session_id}_msg_count
2. 对话摘要存储在 Redis: {session_id}_summary
3. 当 count >= COMPRESS_THRESHOLD 时，发送 MQ 任务
4. MQ Worker 从 Checkpointer 读取消息，生成摘要并更新 Redis
"""

from typing import Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 压缩相关常量
UNCOMPRESSED_WINDOW = 10
COMPRESS_THRESHOLD = 10
KEEP_FRESH_MESSAGES = 5

# Redis Key 前缀
REDIS_KEY_SUMMARY_PREFIX = "stm_summary"
REDIS_KEY_MSG_COUNT_PREFIX = "stm_msg_count"

# MQ Routing Key
ROUTING_SHORTMEM_COMPRESS = "shortmem.compress"


def get_summary_key(session_id: str) -> str:
    """获取指定 session 的摘要 Redis Key"""
    return f"{REDIS_KEY_SUMMARY_PREFIX}:{session_id}"


def get_msg_count_key(session_id: str) -> str:
    """获取指定 session 的消息计数 Redis Key"""
    return f"{REDIS_KEY_MSG_COUNT_PREFIX}:{session_id}"


async def get_short_term_summary(session_id: str) -> str:
    """
    从 Redis 获取指定 session 的短期记忆摘要

    Args:
        session_id: 会话 ID

    Returns:
        摘要内容，如果不存在则返回空字符串
    """
    try:
        from app.infrastructure.redis_client import get_redis
        r = await get_redis()
        summary = await r.get(get_summary_key(session_id))
        if summary:
            return summary.decode() if isinstance(summary, bytes) else summary
        return ""
    except Exception as e:
        logger.warning("获取短期记忆摘要失败", session_id=session_id, error=str(e))
        return ""


async def set_short_term_summary(session_id: str, summary: str) -> bool:
    """
    更新 Redis 中指定 session 的短期记忆摘要

    Args:
        session_id: 会话 ID
        summary: 新的摘要内容

    Returns:
        是否更新成功
    """
    try:
        from app.infrastructure.redis_client import get_redis
        r = await get_redis()
        await r.set(get_summary_key(session_id), summary)
        return True
    except Exception as e:
        logger.error("更新短期记忆摘要失败", session_id=session_id, error=str(e))
        return False


async def get_msg_count(session_id: str) -> int:
    """
    获取指定 session 的未压缩消息计数

    Args:
        session_id: 会话 ID

    Returns:
        消息计数
    """
    try:
        from app.infrastructure.redis_client import get_redis
        r = await get_redis()
        count = await r.get(get_msg_count_key(session_id))
        if count:
            return int(count) if isinstance(count, bytes) else int(count)
        return 0
    except Exception as e:
        logger.warning("获取消息计数失败", session_id=session_id, error=str(e))
        return 0


async def set_msg_count(session_id: str, count: int) -> bool:
    """
    更新 Redis 中指定 session 的消息计数

    Args:
        session_id: 会话 ID
        count: 新的计数

    Returns:
        是否更新成功
    """
    try:
        from app.infrastructure.redis_client import get_redis
        r = await get_redis()
        await r.set(get_msg_count_key(session_id), count)
        return True
    except Exception as e:
        logger.error("更新消息计数失败", session_id=session_id, error=str(e))
        return False


async def increment_msg_count(session_id: str) -> int:
    """
    递增消息计数并返回新值

    Args:
        session_id: 会话 ID

    Returns:
        递增后的计数
    """
    try:
        from app.infrastructure.redis_client import get_redis
        r = await get_redis()
        new_count = await r.incr(get_msg_count_key(session_id))
        return int(new_count)
    except Exception as e:
        logger.error("递增消息计数失败", session_id=session_id, error=str(e))
        return 0


def _serialize_messages(messages: list) -> list:
    """
    将消息列表转换为可 JSON 序列化的字典列表

    Args:
        messages: 原始消息列表（包含 HumanMessage, AIMessage 等对象）

    Returns:
        可序列化的字典列表
    """
    result = []
    for msg in messages:
        if hasattr(msg, "content"):
            msg_dict = {
                "type": getattr(msg, "type", msg.__class__.__name__.lower().replace("message", "")),
                "content": msg.content,
            }
            if hasattr(msg, "additional_kwargs"):
                msg_dict["additional_kwargs"] = msg.additional_kwargs
            result.append(msg_dict)
        elif isinstance(msg, dict):
            result.append(msg)
        else:
            result.append({"type": "unknown", "content": str(msg)})
    return result


async def check_and_trigger_compress(
    session_id: str,
    messages: list,
    old_summary: str,
) -> bool:
    """
    检查是否需要触发压缩，如果是则发送 MQ 消息

    Args:
        session_id: 会话 ID
        messages: 完整的消息列表（将被传递给 MQ Worker）
        old_summary: 当前的摘要

    Returns:
        是否触发了压缩
    """
    try:
        count = len(messages)
        if count >= COMPRESS_THRESHOLD:
            from app.core.memory.mq import MQService
            mq = MQService()
            await mq.publish(
                ROUTING_SHORTMEM_COMPRESS,
                {
                    "session_id": session_id,
                    "messages": _serialize_messages(messages),
                    "old_summary": old_summary,
                }
            )
            logger.info(
                "触发短期记忆压缩",
                session_id=session_id,
                trigger_count=count,
            )
            return True
        return False
    except Exception as e:
        logger.error("检查并触发压缩失败", session_id=session_id, error=str(e))
        return False


async def reset_session_shortmem(session_id: str) -> bool:
    """
    重置指定 session 的短期记忆（摘要和计数都清空）

    Args:
        session_id: 会话 ID

    Returns:
        是否重置成功
    """
    try:
        from app.infrastructure.redis_client import get_redis
        r = await get_redis()
        await r.delete(get_summary_key(session_id))
        await r.delete(get_msg_count_key(session_id))
        logger.info("短期记忆已重置", session_id=session_id)
        return True
    except Exception as e:
        logger.error("重置短期记忆失败", session_id=session_id, error=str(e))
        return False


__all__ = [
    "UNCOMPRESSED_WINDOW",
    "COMPRESS_THRESHOLD",
    "KEEP_FRESH_MESSAGES",
    "ROUTING_SHORTMEM_COMPRESS",
    "get_summary_key",
    "get_msg_count_key",
    "get_short_term_summary",
    "set_short_term_summary",
    "get_msg_count",
    "set_msg_count",
    "increment_msg_count",
    "check_and_trigger_compress",
    "reset_session_shortmem",
]
