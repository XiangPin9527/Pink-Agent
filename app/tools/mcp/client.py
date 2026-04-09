"""
MCP 客户端

支持 SSE 和 Stdio 两种传输方式
"""
from typing import Any, Dict, Optional


class MCPClient:
    """
    MCP 客户端
    
    支持 SSE 和 Stdio 两种传输方式
    """

    def __init__(
        self,
        mcp_id: str,
        mcp_name: str,
        transport_type: str,
        transport_config: Dict[str, Any],
        request_timeout: int = 30000,
    ):
        self.mcp_id = mcp_id
        self.mcp_name = mcp_name
        self.transport_type = transport_type
        self.transport_config = transport_config
        self.request_timeout = request_timeout
        self._client = None

    async def connect(self):
        """连接 MCP 服务器"""
        if self.transport_type == "sse":
            await self._connect_sse()
        elif self.transport_type == "stdio":
            await self._connect_stdio()
        else:
            raise ValueError(f"Unsupported transport type: {self.transport_type}")

    async def _connect_sse(self):
        """SSE 连接"""
        pass

    async def _connect_stdio(self):
        """Stdio 连接"""
        pass

    async def list_tools(self):
        """列出可用工具"""
        if not self._client:
            await self.connect()
        return []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """调用工具"""
        if not self._client:
            await self.connect()
        return {}

    async def close(self):
        """关闭连接"""
        if self._client:
            self._client = None


__all__ = ["MCPClient"]
