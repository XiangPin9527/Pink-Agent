"""
模型工厂

动态创建和管理 LLM 模型实例
"""
from typing import Dict, Optional

from app.config.settings import get_settings
from app.models.base import BaseChatModel
from app.models.providers.openai_compat import OpenAICompatibleModel


class ModelFactory:
    """
    模型工厂
    
    负责创建和缓存 LLM 模型实例
    """

    _instances: Dict[str, BaseChatModel] = {}

    @classmethod
    def get_model(
        cls,
        model_id: str,
        model_name: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> BaseChatModel:
        """
        获取或创建模型实例
        
        Args:
            model_id: 模型唯一标识
            model_name: 模型名称
            api_key: API Key
            base_url: API Base URL
            temperature: 温度参数
            **kwargs: 其他参数
            
        Returns:
            模型实例
        """
        if model_id in cls._instances:
            return cls._instances[model_id]

        settings = get_settings()

        model = OpenAICompatibleModel(
            model_name=model_name,
            api_key=api_key or settings.openai_api_key,
            base_url=base_url or settings.openai_base_url,
            temperature=temperature,
            **kwargs,
        )

        cls._instances[model_id] = model
        return model

    @classmethod
    def clear(cls):
        """清空缓存"""
        cls._instances.clear()


__all__ = ["ModelFactory"]
