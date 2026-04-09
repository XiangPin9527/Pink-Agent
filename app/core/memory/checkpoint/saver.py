import base64
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.infrastructure.redis_client import get_redis
from app.infrastructure.db_client import get_db_pool
from app.utils.logger import get_logger

logger = get_logger(__name__)

REDIS_CP_PREFIX = "cp"


def _thread_id(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("thread_id", "")


def _checkpoint_ns(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("checkpoint_ns", "")


def _cp_key(thread_id: str, ns: str = "") -> str:
    return f"{REDIS_CP_PREFIX}:{thread_id}:{ns}"


def _serde_encode(serde: SerializerProtocol, obj: Any) -> tuple[str, str]:
    type_tag, raw_bytes = serde.dumps_typed(obj)
    b64_str = base64.b64encode(raw_bytes).decode("utf-8")
    return type_tag, b64_str


def _serde_decode(serde: SerializerProtocol, type_tag: str, b64_str: str) -> Any:
    raw_bytes = base64.b64decode(b64_str)
    return serde.loads_typed((type_tag, raw_bytes))


class RedisPostgresSaver(BaseCheckpointSaver):
    """
    两级缓存 CheckpointSaver

    L1: Redis — 存储最新 checkpoint（同步读写，快速）
    L2: PostgreSQL — 存储完整 checkpoint 历史（RabbitMQ 异步写入）

    写入流程:
      1. Redis 同步写入（微秒级，保证下次读取命中）
      2. RabbitMQ 异步投递（微秒级，消费者异步写入 PostgreSQL）
      3. MQ 投递失败时降级为同步写入 PostgreSQL

    Redis 数据结构:
      cp:{thread_id}:{ns}       → 最新 checkpoint (serde typed, base64)
    """

    def __init__(self, serde: SerializerProtocol | None = None):
        super().__init__(serde=serde or JsonPlusSerializer())

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = _thread_id(config)
        ns = _checkpoint_ns(config)
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = None

        cp_type, cp_b64 = _serde_encode(self.serde, checkpoint)
        meta_type, meta_b64 = _serde_encode(self.serde, metadata) if metadata else (None, None)

        try:
            r = await get_redis()
            key = _cp_key(thread_id, ns)
            payload = {
                "checkpoint_id": checkpoint_id,
                "cp_type": cp_type,
                "cp_data": cp_b64,
                "meta_type": meta_type,
                "meta_data": meta_b64,
                "parent_checkpoint_id": parent_checkpoint_id,
            }
            import orjson
            await r.set(key, orjson.dumps(payload).decode("utf-8"))
            logger.debug("Checkpoint 写入 Redis", thread_id=thread_id, checkpoint_id=checkpoint_id)
        except Exception as e:
            logger.warning("Checkpoint 写入 Redis 失败，跳过", thread_id=thread_id, error=str(e))

        try:
            _, cp_raw = self.serde.dumps_typed(checkpoint)
            meta_raw = self.serde.dumps_typed(metadata)[1] if metadata else None
            await self._persist_via_mq(
                thread_id, ns, checkpoint_id, parent_checkpoint_id, cp_raw, meta_raw
            )
        except Exception as e:
            logger.warning("Checkpoint MQ 投递失败，降级同步写入", thread_id=thread_id, error=str(e))
            try:
                await self._persist_to_db(
                    thread_id, ns, checkpoint_id, parent_checkpoint_id, cp_raw, meta_raw
                )
            except Exception as db_err:
                logger.error("Checkpoint 降级同步写入也失败", thread_id=thread_id, error=str(db_err))

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = _thread_id(config)
        ns = _checkpoint_ns(config)
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

        checkpoint, metadata, parent_id = await self._load_from_redis(
            thread_id, ns, checkpoint_id
        )

        if checkpoint is None:
            checkpoint, metadata, parent_id = await self._load_from_db(
                thread_id, ns, checkpoint_id
            )

        if checkpoint is None:
            return None

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ns,
                    "checkpoint_id": checkpoint["id"],
                }
            },
            checkpoint=checkpoint,
            metadata=metadata or CheckpointMetadata(),
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": ns,
                        "checkpoint_id": parent_id,
                    }
                }
                if parent_id
                else None
            ),
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            return

        thread_id = _thread_id(config)
        ns = _checkpoint_ns(config)

        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                sql = """
                    SELECT checkpoint_id, type, checkpoint, metadata, parent_checkpoint_id
                    FROM checkpoints
                    WHERE thread_id = $1 AND checkpoint_ns = $2
                """
                args: list = [thread_id, ns]

                if before:
                    before_id = before.get("configurable", {}).get("checkpoint_id")
                    if before_id:
                        sql += " AND created_at < (SELECT created_at FROM checkpoints WHERE checkpoint_id = $3)"
                        args.append(before_id)

                sql += " ORDER BY created_at DESC"

                if limit:
                    sql += f" LIMIT {limit}"

                rows = await conn.fetch(sql, *args)

                for row in rows:
                    cp_type = row["type"] or "msgpack"
                    cp_data = row["checkpoint"]
                    meta_type = cp_type
                    meta_data = row["metadata"]

                    cp_obj = self.serde.loads_typed((cp_type, cp_data))
                    meta_obj = self.serde.loads_typed((meta_type, meta_data)) if meta_data else CheckpointMetadata()

                    yield CheckpointTuple(
                        config={
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": ns,
                                "checkpoint_id": row["checkpoint_id"],
                            }
                        },
                        checkpoint=cp_obj,
                        metadata=meta_obj,
                        parent_config=(
                            {
                                "configurable": {
                                    "thread_id": thread_id,
                                    "checkpoint_ns": ns,
                                    "checkpoint_id": row["parent_checkpoint_id"],
                                }
                            }
                            if row["parent_checkpoint_id"]
                            else None
                        ),
                    )
        except Exception as e:
            logger.error("从 PostgreSQL 列出 Checkpoint 失败", thread_id=thread_id, error=str(e))

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = _thread_id(config)
        ns = _checkpoint_ns(config)
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id", "")

        try:
            await self._persist_writes_via_mq(thread_id, ns, checkpoint_id, task_id, writes)
        except Exception as e:
            logger.warning("checkpoint_writes MQ 投递失败，降级同步写入", thread_id=thread_id, error=str(e))
            try:
                await self._persist_writes_to_db(thread_id, ns, checkpoint_id, task_id, writes)
            except Exception as db_err:
                logger.error("checkpoint_writes 降级同步写入也失败", thread_id=thread_id, error=str(db_err))

    async def _persist_via_mq(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        parent_checkpoint_id: str | None,
        data: bytes,
        metadata: bytes | None,
    ) -> None:
        from app.core.memory.mq import MQService, ROUTING_CHECKPOINT_PERSIST

        mq = MQService()
        await mq.publish(
            ROUTING_CHECKPOINT_PERSIST,
            {
                "action": "persist",
                "thread_id": thread_id,
                "ns": ns,
                "checkpoint_id": checkpoint_id,
                "parent_checkpoint_id": parent_checkpoint_id,
                "cp_data": base64.b64encode(data).decode(),
                "meta_data": base64.b64encode(metadata).decode() if metadata else None,
            },
        )

    async def _persist_writes_via_mq(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        task_id: str,
        writes: Sequence[tuple[str, Any]],
    ) -> None:
        from app.core.memory.mq import MQService, ROUTING_CHECKPOINT_WRITES

        mq = MQService()
        for idx, (channel, value) in enumerate(writes):
            write_type, write_blob = self.serde.dumps_typed(value)
            await mq.publish(
                ROUTING_CHECKPOINT_WRITES,
                {
                    "action": "put_write",
                    "thread_id": thread_id,
                    "ns": ns,
                    "checkpoint_id": checkpoint_id,
                    "task_id": task_id,
                    "idx": idx,
                    "channel": channel,
                    "write_type": write_type,
                    "write_blob": base64.b64encode(write_blob).decode(),
                },
            )

    async def _load_from_redis(
        self, thread_id: str, ns: str, checkpoint_id: str | None
    ) -> tuple[Checkpoint | None, CheckpointMetadata | None, str | None]:
        try:
            r = await get_redis()
            key = _cp_key(thread_id, ns)
            raw = await r.get(key)
            if not raw:
                return None, None, None

            import orjson
            payload = orjson.loads(raw)

            cp_obj = _serde_decode(self.serde, payload["cp_type"], payload["cp_data"])

            meta_obj = None
            if payload.get("meta_type") and payload.get("meta_data"):
                meta_obj = _serde_decode(self.serde, payload["meta_type"], payload["meta_data"])

            parent_id = payload.get("parent_checkpoint_id")

            if checkpoint_id and cp_obj.get("id") != checkpoint_id:
                return None, None, None

            return cp_obj, meta_obj, parent_id
        except Exception as e:
            logger.warning("从 Redis 加载 Checkpoint 失败", thread_id=thread_id, error=str(e))
            return None, None, None

    async def _load_from_db(
        self, thread_id: str, ns: str, checkpoint_id: str | None
    ) -> tuple[Checkpoint | None, CheckpointMetadata | None, str | None]:
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
                    return None, None, None

                cp_type = row["type"] or "msgpack"
                cp_obj = self.serde.loads_typed((cp_type, row["checkpoint"]))
                meta_obj = self.serde.loads_typed((cp_type, row["metadata"])) if row["metadata"] else None
                parent_id = row["parent_checkpoint_id"]

                return cp_obj, meta_obj, parent_id
        except Exception as e:
            logger.error("从 PostgreSQL 加载 Checkpoint 失败", thread_id=thread_id, error=str(e))
            return None, None, None

    async def _persist_to_db(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        parent_checkpoint_id: str | None,
        data: bytes,
        metadata: bytes | None,
    ) -> None:
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

    async def _persist_writes_to_db(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        task_id: str,
        writes: Sequence[tuple[str, Any]],
    ) -> None:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            for idx, (channel, value) in enumerate(writes):
                write_type, write_blob = self.serde.dumps_typed(value)
                await conn.execute(
                    """
                    INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                    DO UPDATE SET blob = EXCLUDED.blob, type = EXCLUDED.type
                    """,
                    thread_id, ns, checkpoint_id, task_id, idx, channel, write_type, write_blob,
                )


__all__ = ["RedisPostgresSaver"]
