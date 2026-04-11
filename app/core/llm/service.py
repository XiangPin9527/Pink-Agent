"""
LLM 调用服务

提供统一的 LLM 调用接口，支持：
- 动态模型选择
- 记忆注入
- 流式输出
- Token 统计
"""
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config.settings import get_settings
from app.utils.logger import get_logger
from app.utils.trace import TraceContext, set_trace_context

logger = get_logger(__name__)


class LLMService:
    """
    LLM 调用服务
    
    封装 LangChain ChatOpenAI，提供统一的调用接口
    """

    def __init__(self):
        self._model_cache: Dict[str, ChatOpenAI] = {}
        self.settings = get_settings()

    def get_model(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> ChatOpenAI:
        if model_name is None:
            model_name = self.settings.agent_model_name
        """
        获取或创建 LLM 模型实例
        
        Args:
            model_name: 模型名称
            api_key: API Key（可选，默认使用配置）
            base_url: API Base URL（可选，默认使用配置）
            temperature: 温度参数
            **kwargs: 其他模型参数
        """
        cache_key = f"{model_name}_{api_key or 'default'}_{base_url or 'default'}"

        if cache_key not in self._model_cache:
            model = ChatOpenAI(
                model=model_name,
                api_key=api_key or self.settings.openai_api_key,
                base_url=base_url or self.settings.openai_base_url,
                temperature=temperature,
                stream_usage=True,
                **kwargs,
            )
            self._model_cache[cache_key] = model
            logger.info(
                "创建新的 LLM 模型实例",
                model_name=model_name,
                cache_key=cache_key,
            )

        return self._model_cache[cache_key]


_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """获取 LLM 服务单例"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


__all__ = ["LLMService", "get_llm_service"]
