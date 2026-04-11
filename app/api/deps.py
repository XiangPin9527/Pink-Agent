from functools import lru_cache

from app.config.settings import Settings, get_settings


@lru_cache
def get_settings_dep() -> Settings:
    return get_settings()


_orchestrator_engine = None


async def get_orchestrator_engine_dep():
    """获取编排引擎实例（路由+简单/复杂双路径）"""
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
    "get_orchestrator_engine_dep",
    "get_llm_service_dep",
]
