import base64
from typing import Any, Optional
import aio_pika
import orjson

from app.infrastructure.mq_client import get_mq_exchange
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MQPublisher:
    ROUTING_CHECKPOINT_PERSIST = "checkpoint.persist"
    ROUTING_CHECKPOINT_WRITES = "checkpoint.writes"
    ROUTING_LONGTERM_EXTRACT = "longterm.extract"
    ROUTING_SHORTMEM_COMPRESS = "shortmem.compress"
    ROUTING_RAG_INGEST_REPO = "rag.ingest.repo"
    ROUTING_RAG_INGEST_FILES = "rag.ingest.files"

    async def publish(self, routing_key: str, message: dict[str, Any]) -> bool:
        try:
            exchange = await get_mq_exchange()
            body = orjson.dumps(message)
            await exchange.publish(
                aio_pika.Message(
                    body=body,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                ),
                routing_key=routing_key,
            )
            logger.debug("MQ 消息发布成功", routing_key=routing_key)
            return True
        except Exception as e:
            logger.error("MQ 消息发布失败", routing_key=routing_key, error=str(e))
            return False

    async def publish_shortmem_compress(
        self,
        session_id: str,
        messages: list,
        old_summary: str,
        trigger_count: int,
        compress_start: int = 0,
        compress_end: int = 0,
    ) -> bool:
        return await self.publish(self.ROUTING_SHORTMEM_COMPRESS, {
            "session_id": session_id,
            "messages": messages,
            "old_summary": old_summary,
            "trigger_count": trigger_count,
            "compress_start": compress_start,
            "compress_end": compress_end,
        })

    async def publish_longterm_extract(
        self,
        user_id: str,
        thread_id: str,
        messages: list,
        total_msg_count: int,
    ) -> bool:
        return await self.publish(self.ROUTING_LONGTERM_EXTRACT, {
            "user_id": user_id,
            "thread_id": thread_id,
            "messages": messages,
            "total_msg_count": total_msg_count,
        })

    async def publish_checkpoint_persist(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        parent_checkpoint_id: Optional[str],
        cp_data: bytes,
        metadata: Optional[bytes] = None,
    ) -> bool:
        return await self.publish(self.ROUTING_CHECKPOINT_PERSIST, {
            "action": "persist",
            "thread_id": thread_id,
            "ns": ns,
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": parent_checkpoint_id,
            "cp_data": base64.b64encode(cp_data).decode(),
            "meta_data": base64.b64encode(metadata).decode() if metadata else None,
        })

    async def publish_checkpoint_writes(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        task_id: str,
        writes: list[tuple[int, str, str, bytes]],
    ) -> bool:
        for idx, channel, write_type, write_blob in writes:
            ok = await self.publish(self.ROUTING_CHECKPOINT_WRITES, {
                "action": "put_write",
                "thread_id": thread_id,
                "ns": ns,
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "idx": idx,
                "channel": channel,
                "write_type": write_type,
                "write_blob": base64.b64encode(write_blob).decode(),
            })
            if not ok:
                return False
        return True

    async def publish_rag_ingest_repo(
        self,
        task_id: str,
        repo_url: str,
        project_name: str,
        branch: str = "main",
        target_extensions: list[str] | None = None,
    ) -> bool:
        logger.info("mq_publisher开始发布MQ任务")
        return await self.publish(self.ROUTING_RAG_INGEST_REPO, {
            "task_id": task_id,
            "repo_url": repo_url,
            "project_name": project_name,
            "branch": branch,
            "target_extensions": target_extensions,
        })

    async def publish_rag_ingest_files(
        self,
        task_id: str,
        project_name: str,
        files: list[dict[str, str]],
    ) -> bool:
        return await self.publish(self.ROUTING_RAG_INGEST_FILES, {
            "task_id": task_id,
            "project_name": project_name,
            "files": files,
        })


_mq_publisher: Optional[MQPublisher] = None


def get_mq_publisher() -> MQPublisher:
    global _mq_publisher
    if _mq_publisher is None:
        _mq_publisher = MQPublisher()
    return _mq_publisher
