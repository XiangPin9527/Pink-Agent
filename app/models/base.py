from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Optional


class BaseChatModel(ABC):
    """
    模型基类/协议
    """

    @abstractmethod
    async def ainvoke(self, prompt: str, **kwargs) -> str:
        """异步调用模型"""
        pass

    @abstractmethod
    async def astream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """异步流式调用模型"""
        pass

    @abstractmethod
    def bind_tools(self, tools: List):
        """绑定工具"""
        pass


__all__ = ["BaseChatModel"]
