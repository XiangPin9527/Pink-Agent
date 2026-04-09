from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseTool(ABC):
    """
    工具基类
    
    对应 LangChain 的 Tool 协议
    """

    name: str
    description: str

    @abstractmethod
    async def arun(self, *args, **kwargs) -> Any:
        """异步执行工具"""
        pass

    def to_langchain_tool(self):
        """转换为 LangChain Tool"""
        from langchain_core.tools import Tool

        return Tool(
            name=self.name,
            description=self.description,
            func=lambda x: self.arun(x),
        )


__all__ = ["BaseTool"]
