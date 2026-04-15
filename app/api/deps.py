from functools import lru_cache

from app.config.settings import Settings, get_settings
from app.infrastructure.resources import get_app_resources


@lru_cache
def get_settings_dep() -> Settings:
    return get_settings()


async def get_orchestrator_engine_dep():
    """获取编排引擎实例（由应用资源容器统一管理）"""
    resources = await get_app_resources()
    if not resources.initialized:
        await resources.init_all()
    yield resources.orchestrator_graph


def get_llm_service_dep():
    from app.core.llm import get_llm_service
    return get_llm_service()


__all__ = [
    "get_settings_dep",
    "get_orchestrator_engine_dep",
    "get_llm_service_dep",
]
