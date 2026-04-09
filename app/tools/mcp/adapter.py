"""
MCP 工具适配器

将 MCP 工具转换为 LangChain Tool
"""
from typing import List

from app.tools.base import BaseTool
from app.tools.mcp.client import MCPClient


class MCPToolAdapter(BaseTool):
    """
    MCP 工具适配器
    
    将 MCP 工具转换为 LangChain Tool
    """

    def __init__(self, mcp_client: MCPClient, tool_name: str, tool_description: str):
        self.mcp_client = mcp_client
        self.name = tool_name
        self.description = tool_description

    async def arun(self, *args, **kwargs) -> str:
        """执行 MCP 工具"""
        result = await self.mcp_client.call_tool(self.name, kwargs)
        return str(result)


def adapt_mcp_tools(mcp_client: MCPClient) -> List[MCPToolAdapter]:
    """
    将 MCP 客户端的所有工具转换为适配器
    """
    return []


__all__ = ["MCPToolAdapter", "adapt_mcp_tools"]
