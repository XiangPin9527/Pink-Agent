"""
Orchestrator 公共工具函数

提供各节点共享的功能，如长期记忆提取触发、消息提取、长期记忆加载等
"""
from typing import TYPE_CHECKING, List, Optional

from langchain_core.messages import BaseMessage

from app.core.memory.longterm import LONGTERM_EXTRACT_INTERVAL
from app.core.orchestrator.memory import get_mq_service
from app.core.memory.mq import ROUTING_LONGTERM
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.core.memory.loader import MemoryLoader

logger = get_logger(__name__)


def _extract_recent_messages(messages: List[BaseMessage], max_count: int) -> List[BaseMessage]:
    """
    提取最近的指定条消息（不含最后一条，即当前用户消息）

    Args:
        messages: 完整消息列表
        max_count: 最大提取数量

    Returns:
        最近的消息列表（不含最后一条）
    """
    if len(messages) <= 1:
        return []
    return messages[-(max_count + 1):-1]


async def load_ltm_context(
    memory_loader: Optional["MemoryLoader"],
    user_id: str,
    query: str,
) -> str:
    """
    加载长期记忆上下文，返回格式化字符串

    Args:
        memory_loader: 记忆加载器
        user_id: 用户 ID
        query: 查询文本

    Returns:
        格式化的长期记忆上下文字符串
    """
    if not memory_loader or not user_id or not query:
        return ""

    try:
        raw_ltm = await memory_loader.load_long_term_memory(user_id, query)
        ltm_strings = [
            item["value"].get("content", str(item["value"]))
            for item in raw_ltm
            if item.get("value")
        ]
        if ltm_strings:
            return "\n\n已知用户背景信息：\n" + "\n".join(
                f"- {item}" for item in ltm_strings
            )
    except Exception as e:
        logger.warning("加载长期记忆上下文失败", user_id=user_id, error=str(e))

    return ""


async def trigger_longterm_extract(
    user_id: str,
    session_id: str,
    messages: List[BaseMessage],
) -> None:
    """
    检查并触发长期记忆提取

    当新增用户消息数达到阈值（LONGTERM_EXTRACT_INTERVAL = 10）时，
    通过 MQ 异步提取长期记忆并存储到 pgvector

    流程：
    1. 获取上一次提取位置（从 Redis）
    2. 只截取新增消息
    3. 统计新增用户消息数
    4. 如果 >= 10，发布提取任务
    5. 更新 Redis 提取位置

    Args:
        user_id: 用户 ID
        session_id: 会话 ID
        messages: 完整的消息列表
    """
    mq_service = get_mq_service()
    if not mq_service:
        logger.warning("MQ服务未初始化，跳过长期记忆提取", session_id=session_id)
        return

    last_idx = await get_longterm_extract_position(session_id)

    if last_idx >= len(messages):
        last_idx = 0

    new_messages = messages[last_idx:]

    serialized = []
    for msg in new_messages:
        if hasattr(msg, "content") and hasattr(msg, "type"):
            role = "assistant" if msg.type == "ai" else "user" if msg.type == "human" else msg.type
            serialized.append({"role": role, "content": str(msg.content)})
        elif isinstance(msg, dict):
            serialized.append(msg)

    new_user_msgs = [m for m in serialized if m.get("role") == "user"]
    new_msg_count = len(new_user_msgs)

    logger.debug(
        "检查长期记忆提取条件",
        session_id=session_id,
        last_extract_idx=last_idx,
        total_messages=len(messages),
        threshold=LONGTERM_EXTRACT_INTERVAL,
        new_user_msg_count=new_msg_count,
    )

    if new_msg_count >= LONGTERM_EXTRACT_INTERVAL:
        try:
            await mq_service.publish(
                ROUTING_LONGTERM,
                {
                    "user_id": user_id,
                    "thread_id": session_id,
                    "messages": serialized,
                    "total_msg_count": len(messages),
                },
            )
            logger.info(
                "长期记忆提取任务已发布",
                session_id=session_id,
                user_id=user_id,
                last_extract_idx=last_idx,
                new_user_msg_count=new_msg_count,
            )

            await reset_longterm_extract_position(session_id, len(messages))

        except Exception as e:
            logger.error(
                "发布长期记忆提取任务失败",
                session_id=session_id,
                error=str(e),
            )
    else:
        logger.debug(
            "新增用户消息数未达到长期记忆提取阈值",
            session_id=session_id,
            current=new_msg_count,
            threshold=LONGTERM_EXTRACT_INTERVAL,
        )


async def reset_longterm_extract_position(session_id: str, position: int) -> None:
    """
    重置长期记忆提取位置

    用于标记已提取到的消息位置，避免重复提取

    Args:
        session_id: 会话 ID
        position: 提取位置（消息总数）
    """
    try:
        from app.infrastructure.redis_client import get_redis
        r = await get_redis()
        await r.set(f"ltm_last_extract:{session_id}", str(position))
        logger.debug("长期记忆提取位置已更新", session_id=session_id, position=position)
    except Exception as e:
        logger.warning("更新长期记忆提取位置失败", session_id=session_id, error=str(e))


async def get_longterm_extract_position(session_id: str) -> int:
    """
    获取长期记忆提取位置

    Args:
        session_id: 会话 ID

    Returns:
        已提取到的消息位置
    """
    try:
        from app.infrastructure.redis_client import get_redis
        r = await get_redis()
        pos = await r.get(f"ltm_last_extract:{session_id}")
        if pos:
            return int(pos) if isinstance(pos, bytes) else int(pos)
        return 0
    except Exception as e:
        logger.warning("获取长期记忆提取位置失败", session_id=session_id, error=str(e))
        return 0


__all__ = [
    "_extract_recent_messages",
    "load_ltm_context",
    "trigger_longterm_extract",
    "reset_longterm_extract_position",
    "get_longterm_extract_position",
]