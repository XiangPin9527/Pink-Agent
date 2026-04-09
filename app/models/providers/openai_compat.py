from typing import AsyncGenerator, List, Optional

from langchain_openai import ChatOpenAI

from app.models.base import BaseChatModel


class OpenAICompatibleModel(BaseChatModel):
    """
    OpenAI 兼容模型
    
    支持所有 OpenAI 兼容的 API（如 DeepSeek、通义千问等）
    """

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ):
        self.model_name = model_name
        self.llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    async def ainvoke(self, prompt: str, **kwargs) -> str:
        """异步调用模型"""
        response = await self.llm.ainvoke(prompt, **kwargs)
        return response.content

    async def astream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """异步流式调用模型"""
        async for chunk in self.llm.astream(prompt, **kwargs):
            if chunk.content:
                yield chunk.content

    def bind_tools(self, tools: List):
        """绑定工具"""
        return self.llm.bind_tools(tools)


__all__ = ["OpenAICompatibleModel"]
