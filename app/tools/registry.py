"""
工具注册表

提供工具的注册、获取和列表功能
MCP 工具适配后在此注册
"""
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool
from app.utils.logger import get_logger

logger = get_logger(__name__)

_tool_registry: Dict[str, BaseTool] = {}


def register_tool(tool: BaseTool) -> None:
    if not tool.name:
        raise ValueError("Tool must have a name")
    _tool_registry[tool.name] = tool
    logger.info("Tool registered", tool_name=tool.name)


def get_tool(tool_name: str) -> Optional[BaseTool]:
    return _tool_registry.get(tool_name)


def get_all_tools() -> List[BaseTool]:
    return list(_tool_registry.values())


def clear_tools() -> None:
    _tool_registry.clear()
    logger.info("Tool registry cleared")


__all__ = [
    "register_tool",
    "get_tool",
    "get_all_tools",
    "clear_tools",
]