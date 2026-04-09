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


__all__ = [
    "handle_checkpoint_persist",
    "handle_checkpoint_writes",
    "handle_longterm_extract",
]
