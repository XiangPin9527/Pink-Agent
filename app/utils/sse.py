import json
from typing import Any, Dict


class SSEEncoder:
    """
    SSE 编码器
    
    用于将数据编码为 SSE 格式
    """

    @staticmethod
    def encode(data: Dict[str, Any]) -> str:
        """编码为 SSE 格式"""
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def encode_event(event: str, data: Dict[str, Any]) -> str:
        """编码为带事件名的 SSE 格式"""
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


__all__ = ["SSEEncoder"]
