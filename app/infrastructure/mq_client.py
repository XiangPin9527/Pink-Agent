import aio_pika

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_connection: aio_pika.RobustConnection | None = None
_channel: aio_pika.RobustChannel | None = None
_exchange: aio_pika.RobustExchange | None = None


async def get_mq_connection() -> aio_pika.RobustConnection:
    global _connection
    if _connection is None or _connection.is_closed:
        settings = get_settings()
        _connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        logger.info("RabbitMQ 连接初始化完成")
    return _connection


async def get_mq_channel() -> aio_pika.RobustChannel:
    global _channel
    if _channel is None or _channel.is_closed:
        conn = await get_mq_connection()
        settings = get_settings()
        _channel = await conn.channel()
        await _channel.set_qos(prefetch_count=settings.rabbitmq_prefetch_count)
        logger.info("RabbitMQ Channel 初始化完成", prefetch=settings.rabbitmq_prefetch_count)
    return _channel


async def get_mq_exchange() -> aio_pika.RobustExchange:
    global _exchange
    if _exchange is None:
        ch = await get_mq_channel()
        settings = get_settings()
        _exchange = await ch.declare_exchange(
            settings.rabbitmq_exchange,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        logger.info("RabbitMQ Exchange 声明完成", exchange=settings.rabbitmq_exchange)
    return _exchange


async def close_mq():
    global _connection, _channel, _exchange
    if _connection and not _connection.is_closed:
        await _connection.close()
    _connection = None
    _channel = None
    _exchange = None
    logger.info("RabbitMQ 连接已关闭")


__all__ = ["get_mq_connection", "get_mq_channel", "get_mq_exchange", "close_mq"]
