import asyncio
from typing import Any, Callable, Coroutine

import aio_pika
import orjson

from app.infrastructure.mq_client import get_mq_channel, get_mq_exchange
from app.utils.logger import get_logger

logger = get_logger(__name__)

ROUTING_CHECKPOINT_PERSIST = "checkpoint.persist"
ROUTING_CHECKPOINT_WRITES = "checkpoint.writes"
ROUTING_LONGTERM = "longterm.extract"
ROUTING_SHORTMEM_COMPRESS = "shortmem.compress"
ROUTING_RAG_INGEST_REPO = "rag.ingest.repo"
ROUTING_RAG_INGEST_FILES = "rag.ingest.files"

QUEUE_CHECKPOINT_PERSIST = "q.checkpoint.persist"
QUEUE_CHECKPOINT_WRITES = "q.checkpoint.writes"
QUEUE_LONGTERM = "q.longterm.extract"
QUEUE_SHORTMEM_COMPRESS = "q.shortmem.compress"
QUEUE_RAG_INGEST_REPO = "q.rag.ingest.repo"
QUEUE_RAG_INGEST_FILES = "q.rag.ingest.files"
QUEUE_DLQ = "q.dlq"

DLX_NAME = "agent-engine-dlx"

MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]


class MQService:
    """
    基于 RabbitMQ 的可靠消息队列服务

    特性:
    - 持久化队列 + 持久化消息 → RabbitMQ 重启不丢消息
    - ACK/NACK 机制 → 处理成功确认，失败重试
    - 死信队列(DLQ) → 重试耗尽后进入 DLQ，可事后排查
    - RobustConnection → 网络断开自动重连
    - prefetch_count → 控制消费速率，防止 OOM
    """

    def __init__(self):
        self._consumer_tags: list[str] = []
        self._handlers: dict[str, Callable[..., Coroutine]] = {}
        self._running = False

    def register_handler(
        self, queue: str, handler: Callable[..., Coroutine]
    ) -> None:
        self._handlers[queue] = handler

    async def publish(self, routing_key: str, message: dict[str, Any]) -> None:
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
        logger.debug("MQ 消息发布", routing_key=routing_key)

    async def start_workers(self) -> None:
        if self._running:
            return
        self._running = True

        channel = await get_mq_channel()

        dlx = await channel.declare_exchange(
            DLX_NAME, aio_pika.ExchangeType.FANOUT, durable=True
        )

        dlq = await channel.declare_queue(QUEUE_DLQ, durable=True)
        await dlq.bind(dlx, routing_key="")

        exchange = await get_mq_exchange()

        for queue_name, handler in self._handlers.items():
            queue = await channel.declare_queue(
                queue_name,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": DLX_NAME,
                    "x-dead-letter-routing-key": "",
                },
            )

            routing_key = queue_name.replace("q.", "", 1)
            await queue.bind(exchange, routing_key=routing_key)

            consumer_tag = await queue.consume(
                lambda msg, h=handler, q=queue_name: self._on_message(msg, h, q)
            )
            self._consumer_tags.append(consumer_tag)

        logger.info("MQ Workers 启动完成", queues=list(self._handlers.keys()))

    async def stop_workers(self) -> None:
        self._running = False
        channel = await get_mq_channel()
        for tag in self._consumer_tags:
            try:
                await channel.basic_cancel(tag)
            except Exception:
                pass
        self._consumer_tags.clear()
        logger.info("MQ Workers 已停止")

    async def _on_message(
        self,
        message: aio_pika.IncomingMessage,
        handler: Callable[..., Coroutine],
        queue_name: str,
    ) -> None:
        body = orjson.loads(message.body)

        headers = message.headers or {}
        retry_count = int(headers.get("x-retry-count", 0))

        try:
            await handler(body)
            await message.ack()
        except Exception as e:
            retry_count += 1
            if retry_count <= MAX_RETRIES:
                logger.warning(
                    "MQ 消息处理失败，重试",
                    queue=queue_name,
                    retry=retry_count,
                    error=str(e),
                )
                await self._requeue_with_retry(message, body, retry_count)
                await message.ack()
            else:
                logger.error(
                    "MQ 消息处理达到最大重试次数，进入DLQ",
                    queue=queue_name,
                    retry=retry_count,
                    error=str(e),
                )
                await message.nack(requeue=False)

    async def _requeue_with_retry(
        self,
        original: aio_pika.IncomingMessage,
        body: dict,
        retry_count: int,
    ) -> None:
        exchange = await get_mq_exchange()
        routing_key = original.routing_key or ""
        await exchange.publish(
            aio_pika.Message(
                body=orjson.dumps(body),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                headers={"x-retry-count": retry_count},
            ),
            routing_key=routing_key,
        )


_mq_service_instance: MQService | None = None
_mq_service_lock = asyncio.Lock()


def get_mq_service() -> MQService:
    global _mq_service_instance
    if _mq_service_instance is None:
        _mq_service_instance = MQService()
    return _mq_service_instance


async def get_mq_service_instance() -> MQService:
    global _mq_service_instance
    async with _mq_service_lock:
        if _mq_service_instance is None:
            _mq_service_instance = MQService()
    return _mq_service_instance


async def close_mq_service() -> None:
    global _mq_service_instance
    async with _mq_service_lock:
        if _mq_service_instance is not None:
            await _mq_service_instance.stop_workers()
            _mq_service_instance = None


__all__ = [
    "MQService",
    "get_mq_service",
    "get_mq_service_instance",
    "close_mq_service",
    "ROUTING_CHECKPOINT_PERSIST",
    "ROUTING_CHECKPOINT_WRITES",
    "ROUTING_LONGTERM",
    "ROUTING_SHORTMEM_COMPRESS",
    "ROUTING_RAG_INGEST_REPO",
    "ROUTING_RAG_INGEST_FILES",
    "QUEUE_CHECKPOINT_PERSIST",
    "QUEUE_CHECKPOINT_WRITES",
    "QUEUE_LONGTERM",
    "QUEUE_SHORTMEM_COMPRESS",
    "QUEUE_RAG_INGEST_REPO",
    "QUEUE_RAG_INGEST_FILES",
    "QUEUE_DLQ",
]