from typing import Any, Optional
from app.infrastructure.db_client import get_db_pool
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DbService:
    async def persist_checkpoint(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        parent_checkpoint_id: Optional[str],
        data: bytes,
        metadata: Optional[bytes] = None,
    ) -> bool:
        try:
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
                    thread_id, ns, checkpoint_id, parent_checkpoint_id, data, metadata,
                )
            logger.debug("Checkpoint 持久化完成", thread_id=thread_id, checkpoint_id=checkpoint_id)
            return True
        except Exception as e:
            logger.error("持久化checkpoint失败", thread_id=thread_id, error=str(e))
            return False

    async def persist_checkpoint_write(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        task_id: str,
        idx: int,
        channel: str,
        write_type: str,
        write_blob: bytes,
    ) -> bool:
        try:
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
            return True
        except Exception as e:
            logger.error("持久化checkpoint_write失败", thread_id=thread_id, error=str(e))
            return False

    async def get_checkpoint(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                if checkpoint_id:
                    row = await conn.fetchrow(
                        """
                        SELECT checkpoint_id, type, checkpoint, metadata, parent_checkpoint_id
                        FROM checkpoints
                        WHERE thread_id = $1 AND checkpoint_ns = $2 AND checkpoint_id = $3
                        """,
                        thread_id, ns, checkpoint_id,
                    )
                else:
                    row = await conn.fetchrow(
                        """
                        SELECT checkpoint_id, type, checkpoint, metadata, parent_checkpoint_id
                        FROM checkpoints
                        WHERE thread_id = $1 AND checkpoint_ns = $2
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        thread_id, ns,
                    )

                if not row:
                    return None

                return {
                    "checkpoint": row["checkpoint"],
                    "metadata": row["metadata"],
                    "checkpoint_id": row["checkpoint_id"],
                    "type": row["type"],
                    "parent_checkpoint_id": row["parent_checkpoint_id"],
                }
        except Exception as e:
            logger.error("查询checkpoint失败", thread_id=thread_id, error=str(e))
            return None

    async def list_checkpoints(
        self,
        thread_id: str,
        ns: str,
        before_checkpoint_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                sql = """
                    SELECT checkpoint_id, type, checkpoint, metadata, parent_checkpoint_id, created_at
                    FROM checkpoints
                    WHERE thread_id = $1 AND checkpoint_ns = $2
                """
                args: list[Any] = [thread_id, ns]
                arg_idx = 3

                if before_checkpoint_id:
                    sql += f" AND created_at < (SELECT created_at FROM checkpoints WHERE checkpoint_id = ${arg_idx})"
                    args.append(before_checkpoint_id)
                    arg_idx += 1

                sql += " ORDER BY created_at DESC"

                if limit:
                    sql += f" LIMIT ${arg_idx}"
                    args.append(limit)

                rows = await conn.fetch(sql, *args)
                return list(rows)
        except Exception as e:
            logger.error("列出checkpoints失败", thread_id=thread_id, error=str(e))
            return []


_db_service: Optional[DbService] = None


def get_db_service() -> DbService:
    global _db_service
    if _db_service is None:
        _db_service = DbService()
    return _db_service
