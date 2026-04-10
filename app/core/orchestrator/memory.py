"""
Orchestrator 全局记忆组件

提供 memory_loader 和 mq_service 的全局访问能力
"""
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from app.core.memory.loader import MemoryLoader
    from app.core.memory.mq.service import MQService


_memory_loader: Optional["MemoryLoader"] = None
_mq_service: Optional["MQService"] = None


def set_orchestrator_components(
    memory_loader: Optional["MemoryLoader"] = None,
    mq_service: Optional["MQService"] = None,
) -> None:
    """设置 orchestrator 的记忆组件"""
    global _memory_loader, _mq_service
    _memory_loader = memory_loader
    _mq_service = mq_service


def get_memory_loader() -> Optional["MemoryLoader"]:
    """获取 memory_loader"""
    return _memory_loader


def get_mq_service() -> Optional["MQService"]:
    """获取 mq_service"""
    return _mq_service


__all__ = [
    "set_orchestrator_components",
    "get_memory_loader",
    "get_mq_service",
]
