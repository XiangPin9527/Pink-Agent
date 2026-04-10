"""
Agent 执行引擎

基于 LangChain create_agent 的 ReAct Agent 执行引擎，
集成 Checkpoint + Store 记忆系统 + SummarizationMiddleware
"""
from functools import partial
from typing import Any, AsyncGenerator, Optional

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langchain_openai import OpenAIEmbeddings

from app.api.schemas.chat_request import ChatRequest, ChatStreamRequest
from app.api.schemas.chat_response import (
    ChatResponse,
    ChatStreamEvent,
    TraceMetricEvent,
)
from app.core.agent.graph import build_react_agent
from app.core.memory.checkpoint import RedisPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from app.core.memory.mq import (
    MQService,
    ROUTING_LONGTERM,
    ROUTING_SHORTMEM_COMPRESS,
    QUEUE_CHECKPOINT_PERSIST,
    QUEUE_CHECKPOINT_WRITES,
    QUEUE_LONGTERM,
    QUEUE_SHORTMEM_COMPRESS,
)
from app.core.memory.mq.handlers import (
    handle_checkpoint_persist,
    handle_checkpoint_writes,
    handle_longterm_extract,
    handle_shortmem_compress,
)
from app.core.memory.loader import MemoryLoader
from app.core.memory.longterm import LongTermExtractor, LONGTERM_EXTRACT_INTERVAL
from app.core.llm.service import LLMService
from app.utils.logger import get_logger
from app.utils.trace import TraceContext, set_trace_context

logger = get_logger(__name__)

# 全局变量，用于存储 orchestrator 的 checkpointer（供 MQ Handler 使用）
_orchestrator_checkpointer: Optional[RedisPostgresSaver] = None


class AgentEngine:
    """
    Agent 执行引擎

    基于 create_agent 构建 ReAct Agent，
    集成 Checkpoint + Store 记忆系统:
    - Checkpoint (RedisPostgresSaver): 两级缓存，Redis 同步 + PostgreSQL 异步
    - Store (AsyncPostgresStore): 长期记忆，PostgreSQL + pgvector
    - SummarizationMiddleware: 自动摘要 + 消息裁剪（替代自定义短期记忆）
    - MQService: 异步消息队列，驱动长期记忆提取
    """

    def __init__(
        self,
        checkpointer: RedisPostgresSaver | None = None,
        store: AsyncPostgresStore | None = None,
        memory_loader: MemoryLoader | None = None,
        mq_service: MQService | None = None,
    ):
        self._checkpointer = checkpointer
        self._store = store
        self._memory_loader = memory_loader
        self._mq_service = mq_service

        self._llm_service = LLMService()
        self._model = self._llm_service.get_model(
            self._llm_service.settings.agent_model_name
        )

        self.agent = build_react_agent(
            model=self._model,
            checkpointer=checkpointer,
            store=store,
        )

        logger.info(
            "AgentEngine 初始化完成",
            has_checkpointer=checkpointer is not None,
            has_store=store is not None,
            has_memory_loader=memory_loader is not None,
        )

    async def aclose(self):
        if self._store is not None:
            try:
                conn = getattr(self._store, "conn", None)
                if conn is not None and hasattr(conn, "close"):
                    await conn.close()
            except Exception:
                pass

    async def astream_chat(
        self, request: ChatStreamRequest
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        trace_context = TraceContext(
            trace_id=request.session_id,
            user_id=request.user_id,
            session_id=request.session_id,
        )
        set_trace_context(trace_context)

        thread_id = request.session_id

        logger.info(
            f"开始流式 Agent 对话,用户输入：==={request.message}===",
            user_id=request.user_id,
            session_id=request.session_id,
            thread_id=thread_id,
        )

        ltm_strings = await self._load_memory(
            thread_id, request.user_id, request.message
        )

        input_messages = self._build_input_messages(
            request.message,
            long_term_memory=ltm_strings,
        )

        config = self._build_config(thread_id)

        yield ChatStreamEvent(
            type="step_start",
            step=0,
            name="agent",
            text="开始执行 Agent 任务...",
        )

        try:
            total_tokens = 0
            prompt_tokens = 0
            completion_tokens = 0

            async for msg_chunk, metadata in self.agent.astream(
                {"messages": input_messages}, config=config, stream_mode="messages"
            ):
                if isinstance(msg_chunk, AIMessageChunk) and msg_chunk.content:
                    yield ChatStreamEvent(
                        type="content",
                        text=msg_chunk.content,
                    )

                if isinstance(msg_chunk, AIMessageChunk) and msg_chunk.usage_metadata:
                    usage = msg_chunk.usage_metadata
                    total_tokens += usage.get("total_tokens", 0)
                    prompt_tokens += usage.get("input_tokens", 0)
                    completion_tokens += usage.get("output_tokens", 0)

            snapshot = await self.agent.aget_state(config)
            final_state = snapshot.values if snapshot else None

            yield ChatStreamEvent(
                type="done",
                summary="Agent 执行完成",
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

            await self._post_process(thread_id, request.user_id, final_state)

            logger.info(
                "流式 Agent 对话完成",
                session_id=request.session_id,
                thread_id=thread_id,
            )

        except Exception as e:
            logger.error(
                "流式 Agent 对话失败",
                session_id=request.session_id,
                error=str(e),
            )
            yield ChatStreamEvent(
                type="error",
                text=f"执行失败: {str(e)}",
            )

    async def chat(self, request: ChatRequest) -> ChatResponse:
        trace_context = TraceContext(
            trace_id=request.session_id,
            user_id=request.user_id,
            session_id=request.session_id,
        )
        set_trace_context(trace_context)

        thread_id = request.session_id

        logger.info(
            "开始非流式 Agent 对话",
            user_id=request.user_id,
            session_id=request.session_id,
            thread_id=thread_id,
        )

        ltm_strings = await self._load_memory(
            thread_id, request.user_id, request.message
        )

        input_messages = self._build_input_messages(
            request.message,
            long_term_memory=ltm_strings,
        )

        config = self._build_config(thread_id)

        try:
            result = await self.agent.ainvoke(
                {"messages": input_messages}, config=config
            )

            final_messages = result.get("messages", [])

            final_content = ""
            for msg in reversed(final_messages):
                if isinstance(msg, AIMessage) and msg.content:
                    final_content = msg.content
                    break

            snapshot = await self.agent.aget_state(config)
            final_state = snapshot.values if snapshot else None

            await self._post_process(thread_id, request.user_id, final_state)

            total_tokens = 0
            trace_metrics = []
            for msg in final_messages:
                if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                    total_tokens += msg.usage_metadata.get("total_tokens", 0)

            logger.info(
                "非流式 Agent 对话完成",
                session_id=request.session_id,
                thread_id=thread_id,
            )

            return ChatResponse(
                trace_id=request.session_id,
                session_id=request.session_id,
                user_id=request.user_id,
                content=final_content,
                is_completed=True,
                total_steps=len([m for m in final_messages if isinstance(m, AIMessage)]),
                total_tokens=total_tokens,
                trace_metrics=trace_metrics,
            )

        except Exception as e:
            logger.error(
                "非流式 Agent 对话失败",
                session_id=request.session_id,
                error=str(e),
            )
            return ChatResponse(
                trace_id=request.session_id,
                session_id=request.session_id,
                user_id=request.user_id,
                content=f"执行失败: {str(e)}",
                is_completed=False,
                total_steps=0,
                total_tokens=0,
                trace_metrics=[],
            )

    async def _load_memory(
        self, thread_id: str, user_id: str, current_message: str
    ) -> list[str]:
        """
        加载长期记忆

        对话历史由 checkpointer + SummarizationMiddleware 自动管理，
        不再手动加载短期记忆。

        Returns:
            long_term_memory_strings
        """

        if not self._memory_loader:
            return []

        try:
            if user_id and current_message:
                raw_ltm = await self._memory_loader.load_long_term_memory(
                    user_id, current_message
                )
                ltm_strings = [
                    item["value"].get("content", str(item["value"]))
                    for item in raw_ltm
                    if item.get("value")
                ]
                logger.info(
                    "长期记忆整理完成",
                    ltm_strings=ltm_strings

                )
                return ltm_strings
            return []
        except Exception as e:
            logger.warning("长期记忆加载失败", thread_id=thread_id, error=str(e))
            return []

    @staticmethod
    def _build_input_messages(
        message: str,
        long_term_memory: list | None = None,
    ) -> list:
        """
        构建输入消息列表

        对话历史由 checkpointer 自动管理，SummarizationMiddleware 负责摘要和裁剪。
        只传入：
        1. 长期记忆上下文 (SystemMessage, 固定 id 防止累积)
        2. 当前用户消息
        """
        messages = []

        if long_term_memory:
            ltm_context = "已知关于该用户的背景信息：\n" + "\n".join(
                f"- {item}" for item in long_term_memory
            )
            messages.append(
                SystemMessage(
                    content=ltm_context,
                    id="memory_context",
                )
            )

        messages.append(HumanMessage(content=message))

        return messages

    @staticmethod
    def _build_config(thread_id: str) -> dict:
        return {
            "configurable": {
                "thread_id": thread_id,
            },
        }

    async def _post_process(
        self, thread_id: str, user_id: str, final_state: dict | None
    ) -> None:
        if not self._mq_service or not final_state:
            return

        try:
            messages = []
            if final_state.get("messages"):
                for msg in final_state["messages"]:
                    if hasattr(msg, "content") and hasattr(msg, "type"):
                        role = "assistant" if msg.type == "ai" else "user" if msg.type == "human" else msg.type
                        messages.append({"role": role, "content": str(msg.content)})
                    elif isinstance(msg, dict):
                        messages.append(msg)

            if not messages:
                return

            last_idx = 0
            try:
                from app.infrastructure.redis_client import get_redis
                r = await get_redis()
                last_idx_str = await r.get(f"ltm_last_extract:{thread_id}")
                if last_idx_str:
                    last_idx = int(last_idx_str)
            except Exception:
                pass

            if last_idx > len(messages):
                last_idx = 0

            new_messages = messages[last_idx:]
            new_user_msgs = [m for m in new_messages if m.get("role") == "user"]

            if len(new_user_msgs) >= LONGTERM_EXTRACT_INTERVAL:
                await self._mq_service.publish(
                    ROUTING_LONGTERM,
                    {
                        "user_id": user_id,
                        "thread_id": thread_id,
                        "messages": new_messages,
                        "total_msg_count": len(messages),
                    },
                )

            logger.debug("后处理 MQ 消息已发布", thread_id=thread_id)
        except Exception as e:
            logger.warning("后处理失败", thread_id=thread_id, error=str(e))


_agent_engine: Optional[AgentEngine] = None


def get_agent_engine() -> AgentEngine:
    """获取 AgentEngine 单例（无状态版本，不使用 Checkpoint/Store）"""
    global _agent_engine
    if _agent_engine is None:
        _agent_engine = AgentEngine()
    return _agent_engine


async def create_agent_engine_with_memory() -> AgentEngine:
    """创建带完整记忆系统的 AgentEngine"""
    from app.config.settings import get_settings

    settings = get_settings()

    checkpointer = RedisPostgresSaver()

    embedder = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        dimensions=settings.openai_embedding_dims,
        check_embedding_ctx_length=False,
    )
    from psycopg_pool import AsyncConnectionPool

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
            "embed": embedder,
            "fields": ["content", "category"],
        },
    )
    await store.setup()

    memory_loader = MemoryLoader(store=store)

    mq_service = MQService()

    llm_service = LLMService()
    llm = llm_service.get_model(settings.agent_model_name)

    longterm_extractor = LongTermExtractor(llm=llm, store=store)

    mq_service.register_handler(QUEUE_CHECKPOINT_PERSIST, handle_checkpoint_persist)
    mq_service.register_handler(QUEUE_CHECKPOINT_WRITES, handle_checkpoint_writes)
    mq_service.register_handler(
        QUEUE_LONGTERM,
        partial(handle_longterm_extract, longterm_extractor),
    )

    await mq_service.start_workers()

    engine = AgentEngine(
        checkpointer=checkpointer,
        store=store,
        memory_loader=memory_loader,
        mq_service=mq_service,
    )

    return engine


async def create_orchestrator_engine():
    """创建编排引擎（路由+简单/复杂双路径，带完整记忆系统）"""
    from app.config.settings import get_settings
    from app.core.memory.checkpoint.saver import RedisPostgresSaver
    from app.core.orchestrator.graph import build_orchestrator_graph
    from app.core.orchestrator.memory import set_orchestrator_components
    from app.core.memory.loader import MemoryLoader
    from app.core.memory.mq.service import MQService
    from app.core.memory.mq.handlers import (
        handle_checkpoint_persist,
        handle_checkpoint_writes,
        handle_longterm_extract,
    )
    from psycopg_pool import AsyncConnectionPool
    from langchain_openai import OpenAIEmbeddings
    from langgraph.store.postgres.aio import AsyncPostgresStore

    settings = get_settings()

    checkpointer = RedisPostgresSaver()

    embedder = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        dimensions=settings.openai_embedding_dims,
        check_embedding_ctx_length=False,
    )

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
            "embed": embedder,
            "fields": ["content", "category"],
        },
    )
    await store.setup()

    memory_loader = MemoryLoader(store=store)

    from app.core.memory.longterm.extractor import LongTermExtractor
    from app.core.llm.service import get_llm_service

    llm = get_llm_service().get_model()
    longterm_extractor = LongTermExtractor(llm=llm, store=store)

    mq_service = MQService()

    from app.core.memory.mq.service import (
        QUEUE_CHECKPOINT_PERSIST,
        QUEUE_CHECKPOINT_WRITES,
        QUEUE_LONGTERM,
        QUEUE_SHORTMEM_COMPRESS,
    )

    mq_service.register_handler(QUEUE_CHECKPOINT_PERSIST, handle_checkpoint_persist)
    mq_service.register_handler(QUEUE_CHECKPOINT_WRITES, handle_checkpoint_writes)
    mq_service.register_handler(
        QUEUE_LONGTERM,
        lambda ch, body: handle_longterm_extract(longterm_extractor, ch, body),
    )
    mq_service.register_handler(QUEUE_SHORTMEM_COMPRESS, handle_shortmem_compress)

    await mq_service.start_workers()

    set_orchestrator_components(memory_loader=memory_loader, mq_service=mq_service)

    graph = build_orchestrator_graph()
    compiled_graph = graph.compile(checkpointer=checkpointer, store=store)

    logger.info(
        "OrchestratorEngine 创建完成",
        has_checkpointer=True,
        has_store=True,
        has_memory_loader=True,
        has_mq_service=True,
    )

    return compiled_graph


__all__ = [
    "AgentEngine",
    "get_agent_engine",
    "create_agent_engine_with_memory",
    "create_orchestrator_engine",
]
