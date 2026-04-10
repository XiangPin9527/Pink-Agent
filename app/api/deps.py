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


_orchestrator_engine = None


async def get_orchestrator_engine_dep():
    """
    获取编排引擎实例（路由+简单/复杂双路径）
    """
    global _orchestrator_engine
    if _orchestrator_engine is None:
        from app.core.agent.engine import create_orchestrator_engine
        _orchestrator_engine = await create_orchestrator_engine()
    yield _orchestrator_engine


def get_llm_service_dep():
    from app.core.llm import get_llm_service
    return get_llm_service()


__all__ = [
    "get_settings_dep",
    "get_agent_engine_dep",
    "get_orchestrator_engine_dep",
    "get_llm_service_dep",
]