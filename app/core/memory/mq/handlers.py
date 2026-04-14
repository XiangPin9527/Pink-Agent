import base64
from typing import Any

from app.utils.logger import get_logger
from app.infrastructure.db_service import get_db_service
from app.infrastructure.redis_service import get_redis_service

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

    db_service = get_db_service()
    await db_service.persist_checkpoint(
        thread_id, ns, checkpoint_id, parent_checkpoint_id, cp_data, meta_data
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

    db_service = get_db_service()
    await db_service.persist_checkpoint_write(
        thread_id, ns, checkpoint_id, task_id, idx, channel, write_type, write_blob
    )
    logger.debug("Checkpoint write 持久化完成", thread_id=thread_id, checkpoint_id=checkpoint_id)


async def handle_longterm_extract(message: dict[str, Any]) -> None:
    user_id = message.get("user_id", "")
    thread_id = message.get("thread_id", "")
    msgs = message.get("messages", [])
    total_msg_count = message.get("total_msg_count", 0)
    if user_id and msgs:
        from app.core.memory.longterm.extractor import LongTermExtractor
        from app.core.llm.service import get_llm_service
        from langgraph.store.postgres.aio import AsyncPostgresStore
        from psycopg_pool import AsyncConnectionPool
        from app.config.settings import get_settings

        settings = get_settings()
        llm = get_llm_service().get_model()

        async def _configure_conn(conn):
            await conn.set_autocommit(True)

        pg_pool = AsyncConnectionPool(
            conninfo=settings.database_url.replace("+asyncpg", ""),
            min_size=2,
            max_size=10,
            configure=_configure_conn,
        )
        await pg_pool.open()

        store = AsyncPostgresStore(
            conn=pg_pool,
            index={
                "dims": settings.openai_embedding_dims,
                "embed": llm,
                "fields": ["content", "category"],
            },
        )
        await store.setup()

        longterm_extractor = LongTermExtractor(llm=llm, store=store)
        await longterm_extractor.extract_and_store(user_id, thread_id, msgs)
        redis_service = get_redis_service()
        await redis_service.set_longterm_extract_position(thread_id, total_msg_count)
        logger.debug("长期记忆提取位置已更新", thread_id=thread_id, position=total_msg_count)


async def handle_shortmem_compress(message: dict[str, Any]) -> None:
    """
    处理短期记忆压缩任务

    从 MQ 消息中获取待压缩的消息内容，生成摘要并更新 Redis

    Args:
        message: MQ 消息，包含 session_id, messages, old_summary
    """
    from app.core.memory.shortmem import (
        KEEP_FRESH_MESSAGES,
        set_short_term_summary,
        reset_msg_count_after_compress,
    )

    session_id = message.get("session_id", "")
    messages = message.get("messages", [])
    old_summary = message.get("old_summary", "")

    if not session_id:
        logger.warning("短期记忆压缩任务缺少 session_id")
        return

    if not messages:
        logger.info("无消息需要压缩", session_id=session_id)
        return

    keep_count = KEEP_FRESH_MESSAGES
    if len(messages) <= keep_count:
        logger.info("消息数量少于保留数量，无需压缩", session_id=session_id, msg_count=len(messages))
        return

    to_compress = messages[:-keep_count]
    summary_text = await _generate_summary(to_compress, old_summary, session_id)

    success = await set_short_term_summary(session_id, summary_text)
    if success:
        await reset_msg_count_after_compress(session_id)
        logger.info(
            "短期记忆压缩完成",
            session_id=session_id,
            compressed_count=len(to_compress),
            kept_count=keep_count,
            summary_len=len(summary_text),
        )
    else:
        logger.error("更新短期记忆摘要失败", session_id=session_id)


async def _generate_summary(
    messages: list, old_summary: str, session_id: str
) -> str:
    """
    使用 LLM 生成对话摘要

    Args:
        messages: 待压缩的消息列表
        old_summary: 旧的摘要
        session_id: 会话 ID

    Returns:
        新的摘要文本
    """
    from app.core.llm.service import get_llm_service
    from langchain_core.messages import HumanMessage, AIMessage

    if not messages:
        return old_summary

    message_texts = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "用户"
            content = msg.content
        elif isinstance(msg, AIMessage):
            role = "助手"
            content = msg.content
        elif isinstance(msg, dict):
            role = "用户" if msg.get("type") == "human" else "助手"
            content = msg.get("content", "")
        else:
            role = msg.__class__.__name__
            content = msg.content if hasattr(msg, "content") else str(msg)
        message_texts.append(f"{role}: {content}")

    full_text = "\n".join(message_texts)

    prompt_parts = ["请将以下对话内容压缩成简洁的摘要，保留关键信息、用户意图和重要结论。", ""]

    if old_summary:
        prompt_parts.append(f"【之前的摘要】:\n{old_summary}\n")

    prompt_parts.append("【待压缩的对话】:")
    prompt_parts.append(full_text)
    prompt_parts.append("")
    prompt_parts.append("请生成一段简洁的摘要（不超过200字），涵盖对话的核心内容：")

    prompt = "\n".join(prompt_parts)

    try:
        llm = get_llm_service().get_model()
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        summary = response.content if hasattr(response, "content") else str(response)
        summary = summary.strip()
        logger.debug("摘要生成成功", session_id=session_id, summary_len=len(summary))
        return summary
    except Exception as e:
        logger.error("生成摘要失败", session_id=session_id, error=str(e))
        return old_summary


async def handle_rag_ingest_repo(message: dict[str, Any]) -> None:
    task_id = message.get("task_id", "")
    repo_url = message.get("repo_url", "")
    project_name = message.get("project_name", "")
    branch = message.get("branch", "main")
    target_extensions = message.get("target_extensions")

    if not repo_url or not project_name:
        logger.warning("RAG 仓库入库任务缺少必要参数", task_id=task_id)
        return

    try:
        redis_service = get_redis_service()
        await redis_service.set_rag_task_status(task_id, "processing")

        from app.core.rag.engine import get_rag_engine
        rag_engine = get_rag_engine()
        logger.info("MQ接收到嵌入向量库消息，开始执行处理")
        repo_info = await rag_engine.ingest_repo(
            repo_url=repo_url,
            project_name=project_name,
            branch=branch,
            target_extensions=target_extensions,
        )

        await redis_service.set_rag_task_status(task_id, "completed", {
            "project_name": project_name,
            "file_count": repo_info.file_count,
            "total_size": repo_info.total_size,
        })
        logger.info(
            "RAG 仓库入库完成",
            task_id=task_id,
            project_name=project_name,
            file_count=repo_info.file_count,
        )
    except Exception as e:
        logger.error("RAG 仓库入库失败", task_id=task_id, error=str(e))
        try:
            await redis_service.set_rag_task_status(task_id, "failed", {"error": str(e)})
        except Exception:
            pass


async def handle_rag_ingest_files(message: dict[str, Any]) -> None:
    task_id = message.get("task_id", "")
    project_name = message.get("project_name", "")
    files = message.get("files", [])

    if not project_name or not files:
        logger.warning("RAG 文件入库任务缺少必要参数", task_id=task_id)
        return

    try:
        redis_service = get_redis_service()
        await redis_service.set_rag_task_status(task_id, "processing")

        from app.core.rag.engine import get_rag_engine
        rag_engine = get_rag_engine()
        inserted = await rag_engine.ingest_files(
            project_name=project_name,
            files=files,
        )

        await redis_service.set_rag_task_status(task_id, "completed", {
            "project_name": project_name,
            "inserted": inserted,
        })
        logger.info("RAG 文件入库完成", task_id=task_id, project_name=project_name, inserted=inserted)
    except Exception as e:
        logger.error("RAG 文件入库失败", task_id=task_id, error=str(e))
        try:
            await redis_service.set_rag_task_status(task_id, "failed", {"error": str(e)})
        except Exception:
            pass


__all__ = [
    "handle_checkpoint_persist",
    "handle_checkpoint_writes",
    "handle_longterm_extract",
    "handle_shortmem_compress",
    "handle_rag_ingest_repo",
    "handle_rag_ingest_files",
]
