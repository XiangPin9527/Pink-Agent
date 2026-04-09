from functools import lru_cache

from app.config.settings import Settings, get_settings


@lru_cache
def get_settings_dep() -> Settings:
    return get_settings()


_agent_engine_with_memory = None


async def get_agent_engine_dep():
    """
    获取带记忆系统的 AgentEngine 实例

    优先使用 create_agent_engine_with_memory() 创建带 Checkpoint/Store 的实例
    """
    global _agent_engine_with_memory
    if _agent_engine_with_memory is None:
        from app.core.agent.engine import create_agent_engine_with_memory
        _agent_engine_with_memory = await create_agent_engine_with_memory()
    yield _agent_engine_with_memory


def get_llm_service_dep():
    from app.core.llm import get_llm_service
    return get_llm_service()


__all__ = [
    "get_settings_dep",
    "get_agent_engine_dep",
    "get_llm_service_dep",
]
