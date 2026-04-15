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

from app.utils.logger import get_logger
from app.infrastructure.redis_service import get_redis_service
from app.infrastructure.db_service import get_db_service
from app.infrastructure.mq_publisher import get_mq_publisher
from app.core.memory.mq.service import ROUTING_CHECKPOINT_PERSIST, ROUTING_CHECKPOINT_WRITES

logger = get_logger(__name__)


def _thread_id(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("thread_id", "")


def _checkpoint_ns(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("checkpoint_ns", "")


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

    L1: Redis — 存储所有 checkpoint，按 checkpoint_id 区分（同步读写，快速）
    L2: PostgreSQL — 存储完整 checkpoint 历史（RabbitMQ 异步写入）

    写入流程:
      1. Redis 同步写入（微秒级，保证下次读取命中）
      2. RabbitMQ 异步投递（微秒级，消费者异步写入 PostgreSQL）
      3. MQ 投递失败时降级为同步写入 PostgreSQL

    Redis 数据结构:
      cp:{thread_id}:{ns}:{checkpoint_id}  → 单个 checkpoint (serde typed, base64)
      cp_ids:{thread_id}:{ns}              → SET，存储所有 checkpoint_id
      TTL: 3 天
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
            redis_service = get_redis_service()
            payload = {
                "checkpoint_id": checkpoint_id,
                "cp_type": cp_type,
                "cp_data": cp_b64,
                "meta_type": meta_type,
                "meta_data": meta_b64,
                "parent_checkpoint_id": parent_checkpoint_id,
            }
            await redis_service.set_checkpoint(thread_id, ns, checkpoint_id, payload)
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

        checkpoint_ids: list[str] = []
        redis_has_all = True

        try:
            redis_service = get_redis_service()
            checkpoint_ids = await redis_service.get_checkpoint_ids(thread_id, ns)
        except Exception as e:
            logger.warning("从 Redis 获取 checkpoint IDs 失败，降级到 PostgreSQL", thread_id=thread_id, error=str(e))
            redis_has_all = False

        if redis_has_all and checkpoint_ids:
            before_checkpoint_id = None
            if before:
                before_checkpoint_id = before.get("configurable", {}).get("checkpoint_id")

            filtered_ids = checkpoint_ids
            if before_checkpoint_id:
                filtered_ids = [cid for cid in checkpoint_ids if cid < before_checkpoint_id]

            if limit:
                filtered_ids = filtered_ids[-limit:]

            for cp_id in filtered_ids:
                try:
                    checkpoint, metadata, parent_id = await self._load_from_redis(
                        thread_id, ns, cp_id
                    )
                    if checkpoint:
                        yield CheckpointTuple(
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
                except Exception as e:
                    logger.warning("从 Redis 加载 Checkpoint 失败，跳过", thread_id=thread_id, checkpoint_id=cp_id, error=str(e))
                    continue
        else:
            try:
                db_service = get_db_service()
                before_checkpoint_id = None
                if before:
                    before_checkpoint_id = before.get("configurable", {}).get("checkpoint_id")

                rows = await db_service.list_checkpoints(thread_id, ns, before_checkpoint_id, limit)

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
        mq_publisher = get_mq_publisher()
        await mq_publisher.publish_checkpoint_persist(
            thread_id, ns, checkpoint_id, parent_checkpoint_id, data, metadata
        )

    async def _persist_writes_via_mq(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        task_id: str,
        writes: Sequence[tuple[str, Any]],
    ) -> None:
        mq_publisher = get_mq_publisher()
        serialized_writes = []
        for idx, (channel, value) in enumerate(writes):
            write_type, write_blob = self.serde.dumps_typed(value)
            serialized_writes.append((idx, channel, write_type, write_blob))
        await mq_publisher.publish_checkpoint_writes(
            thread_id, ns, checkpoint_id, task_id, serialized_writes
        )

    async def _load_from_redis(
        self, thread_id: str, ns: str, checkpoint_id: str | None
    ) -> tuple[Checkpoint | None, CheckpointMetadata | None, str | None]:
        try:
            redis_service = get_redis_service()

            if checkpoint_id:
                payload = await redis_service.get_checkpoint_by_id(thread_id, ns, checkpoint_id)
            else:
                payload = await redis_service.get_checkpoint(thread_id, ns)

            if not payload:
                return None, None, None

            cp_obj = _serde_decode(self.serde, payload["cp_type"], payload["cp_data"])

            meta_obj = None
            if payload.get("meta_type") and payload.get("meta_data"):
                meta_obj = _serde_decode(self.serde, payload["meta_type"], payload["meta_data"])

            parent_id = payload.get("parent_checkpoint_id")

            if checkpoint_id and cp_obj.get("id") != checkpoint_id:
                return None, None, None

            return cp_obj, meta_obj, parent_id
        except Exception as e:
            logger.warning("从 Redis 加载 Checkpoint 失败", thread_id=thread_id, checkpoint_id=checkpoint_id, error=str(e))
            return None, None, None

    async def _load_from_db(
        self, thread_id: str, ns: str, checkpoint_id: str | None
    ) -> tuple[Checkpoint | None, CheckpointMetadata | None, str | None]:
        try:
            db_service = get_db_service()
            row = await db_service.get_checkpoint(thread_id, ns, checkpoint_id)

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
        db_service = get_db_service()
        await db_service.persist_checkpoint(
            thread_id, ns, checkpoint_id, parent_checkpoint_id, data, metadata
        )

    async def _persist_writes_to_db(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        task_id: str,
        writes: Sequence[tuple[str, Any]],
    ) -> None:
        db_service = get_db_service()
        for idx, (channel, value) in enumerate(writes):
            write_type, write_blob = self.serde.dumps_typed(value)
            await db_service.persist_checkpoint_write(
                thread_id, ns, checkpoint_id, task_id, idx, channel, write_type, write_blob
            )


__all__ = ["RedisPostgresSaver"]
