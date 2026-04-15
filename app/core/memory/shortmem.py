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

from app.utils.logger import get_logger
from app.infrastructure.redis_service import get_redis_service
from app.infrastructure.mq_publisher import get_mq_publisher

logger = get_logger(__name__)

COMPRESS_THRESHOLD = 30
KEEP_FRESH_MESSAGES = 20

ROUTING_SHORTMEM_COMPRESS = "shortmem.compress"


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


async def get_short_term_summary(session_id: str) -> str:
    """
    从 Redis 获取指定 session 的短期记忆摘要

    Args:
        session_id: 会话 ID

    Returns:
        摘要内容，如果不存在则返回空字符串
    """
    redis_service = get_redis_service()
    return await redis_service.get_short_term_summary(session_id)


async def set_short_term_summary(session_id: str, summary: str) -> bool:
    """
    更新 Redis 中指定 session 的短期记忆摘要

    Args:
        session_id: 会话 ID
        summary: 新的摘要内容

    Returns:
        是否更新成功
    """
    redis_service = get_redis_service()
    return await redis_service.set_short_term_summary(session_id, summary)


async def get_msg_count(session_id: str) -> int:
    """
    获取指定 session 的未压缩消息计数

    Args:
        session_id: 会话 ID

    Returns:
        消息计数
    """
    redis_service = get_redis_service()
    return await redis_service.get_msg_count(session_id)


async def set_msg_count(session_id: str, count: int) -> bool:
    """
    更新 Redis 中指定 session 的消息计数

    Args:
        session_id: 会话 ID
        count: 新的计数

    Returns:
        是否更新成功
    """
    redis_service = get_redis_service()
    return await redis_service.set_msg_count(session_id, count)


async def increment_msg_count(session_id: str) -> int:
    """
    递增消息计数并返回新值

    Args:
        session_id: 会话 ID

    Returns:
        递增后的计数
    """
    redis_service = get_redis_service()
    return await redis_service.increment_msg_count(session_id)


async def get_last_compress_idx(session_id: str) -> int:
    """
    获取上次压缩截止位置

    Args:
        session_id: 会话 ID

    Returns:
        上次压缩的截止位置索引，0表示首次压缩
    """
    redis_service = get_redis_service()
    return await redis_service.get_last_compress_idx(session_id)


async def set_last_compress_idx(session_id: str, idx: int) -> bool:
    """
    设置上次压缩截止位置

    Args:
        session_id: 会话 ID
        idx: 压缩截止位置索引

    Returns:
        是否设置成功
    """
    redis_service = get_redis_service()
    return await redis_service.set_last_compress_idx(session_id, idx)


async def increment_and_check_compress(
    session_id: str,
    messages: list,
    old_summary: str,
) -> bool:
    """
    递增消息计数并检查是否需要触发压缩

    这是主要的入口函数，每次处理完用户消息后调用：
    1. 递增 Redis 计数器
    2. 检查是否达到压缩阈值
    3. 如果达到阈值，计算增量压缩范围并触发 MQ 任务

    增量压缩逻辑:
    - 从上次压缩截止位置(last_compress_idx)开始
    - 到总消息数减去保留新鲜消息的数量(total - KEEP_FRESH_MESSAGES)结束
    - 只压缩新增的消息，避免重复压缩已摘要的内容

    Args:
        session_id: 会话 ID
        messages: 当前会话的全部消息列表
        old_summary: 当前的摘要

    Returns:
        是否触发了压缩
    """
    try:
        new_count = await increment_msg_count(session_id)
        logger.debug(
            "消息计数已递增",
            session_id=session_id,
            new_count=new_count,
        )

        if new_count >= COMPRESS_THRESHOLD:
            last_idx = await get_last_compress_idx(session_id)
            total_msgs = len(messages)
            compress_end = total_msgs - KEEP_FRESH_MESSAGES

            if compress_end > last_idx:
                mq_publisher = get_mq_publisher()
                await mq_publisher.publish_shortmem_compress(
                    session_id,
                    _serialize_messages(messages),
                    old_summary,
                    new_count,
                    last_idx,
                    compress_end,
                )
                logger.info(
                    "触发短期记忆压缩",
                    session_id=session_id,
                    last_idx=last_idx,
                    compress_end=compress_end,
                    total_msgs=total_msgs,
                )
            else:
                logger.debug(
                    "无新消息需要压缩",
                    session_id=session_id,
                    last_idx=last_idx,
                    compress_end=compress_end,
                )
            return True
        return False
    except Exception as e:
        logger.error("递增计数并检查压缩失败", session_id=session_id, error=str(e))
        return False


async def reset_msg_count_after_compress(session_id: str, last_compress_idx: int) -> bool:
    """
    压缩完成后重置消息计数器并更新压缩位置

    压缩完成后执行：
    1. 将计数器重置为 KEEP_FRESH_MESSAGES
    2. 更新压缩截止位置(last_compress_idx)

    Args:
        session_id: 会话 ID
        last_compress_idx: 本次压缩的截止位置索引

    Returns:
        是否重置成功
    """
    redis_service = get_redis_service()
    try:
        await redis_service.set_msg_count(session_id, KEEP_FRESH_MESSAGES)
        await redis_service.set_last_compress_idx(session_id, last_compress_idx)
        logger.debug(
            "压缩后状态已重置",
            session_id=session_id,
            new_count=KEEP_FRESH_MESSAGES,
            last_compress_idx=last_compress_idx,
        )
        return True
    except Exception as e:
        logger.error("重置压缩后状态失败", session_id=session_id, error=str(e))
        return False


async def init_msg_count_if_needed(session_id: str, has_summary: bool) -> None:
    """
    如果需要，初始化消息计数器

    首次建立摘要时，初始化计数器为 KEEP_FRESH_MESSAGES

    Args:
        session_id: 会话 ID
        has_summary: 是否已有摘要
    """
    if has_summary:
        current = await get_msg_count(session_id)
        if current == 0:
            await set_msg_count(session_id, KEEP_FRESH_MESSAGES)
            logger.debug(
                "已初始化计数器（有摘要情况）",
                session_id=session_id,
                init_count=KEEP_FRESH_MESSAGES,
            )


__all__ = [
    "COMPRESS_THRESHOLD",
    "KEEP_FRESH_MESSAGES",
    "ROUTING_SHORTMEM_COMPRESS",
    "get_short_term_summary",
    "set_short_term_summary",
    "get_msg_count",
    "set_msg_count",
    "increment_msg_count",
    "get_last_compress_idx",
    "set_last_compress_idx",
    "increment_and_check_compress",
    "reset_msg_count_after_compress",
    "init_msg_count_if_needed",
]
