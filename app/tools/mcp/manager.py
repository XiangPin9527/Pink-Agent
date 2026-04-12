"""
MCP 服务管理器

集中管理多个 MCP 服务器连接和工具
"""
import os
from typing import Any, Dict, List, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import BaseTool

from app.utils.logger import get_logger
from app.tools.mcp.config import MCPConfigLoader, MCPServerConfig

logger = get_logger(__name__)


class MCPServiceManager:
    """
    MCP 服务管理器

    核心功能：
    1. 管理 MultiServerMCPClient 实例
    2. 集中加载/缓存工具
    3. 按标签获取工具
    4. 生命周期管理
    """

    def __init__(self):
        self._client: Optional[MultiServerMCPClient] = None
        self._configs: Dict[str, MCPServerConfig] = {}
        self._tools: Optional[List[BaseTool]] = None
        self._tools_by_tag: Optional[Dict[str, List[BaseTool]]] = None
        self._initialized = False

    def configure(self, configs: Dict[str, MCPServerConfig]) -> None:
        """
        配置 MCP 服务器

        Args:
            configs: 服务器名称 -> MCPServerConfig 的映射
        """
        self._configs = configs
        self._initialized = False
        logger.info("MCP 服务配置已更新", servers=list(configs.keys()))

    def _load_config_from_yaml(self) -> Dict[str, MCPServerConfig]:
        """从 YAML 文件加载配置"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "mcp.yaml"
        )
        return MCPConfigLoader.from_yaml(config_path)

    async def initialize(self) -> None:
        """初始化 MCP 客户端并加载工具"""
        if self._initialized:
            return

        if not self._configs:
            self._configs = self._load_config_from_yaml()

        if not self._configs:
            logger.info("没有配置 MCP 服务器")
            self._initialized = True
            return

        enabled_configs = {
            name: config
            for name, config in self._configs.items()
            if config.enabled
        }

        if not enabled_configs:
            logger.info("没有启用的 MCP 服务器")
            self._initialized = True
            return

        connections = {}
        for name, config in enabled_configs.items():
            connections[name] = MCPConfigLoader.build_connection_config(config)

        logger.info("正在初始化 MCP 客户端", servers=list(connections.keys()))

        try:
            self._client = MultiServerMCPClient(connections)
            self._tools = await self._client.get_tools()
        except Exception as e:
            logger.error("MCP 客户端初始化失败", error=str(e))
            self._tools = []
            self._initialized = True
            return

        self._build_tools_index()

        logger.info(
            "MCP 服务初始化完成",
            server_count=len(enabled_configs),
            total_tools=len(self._tools) if self._tools else 0,
            tags=list(self._tools_by_tag.keys()) if self._tools_by_tag else [],
        )

        self._initialized = True

    def _build_tools_index(self) -> None:
        """构建工具索引，按标签分组"""
        if not self._tools:
            self._tools_by_tag = {"all": []}
            return

        self._tools_by_tag = {"all": list(self._tools)}

        for tool in self._tools:
            for name, config in self._configs.items():
                if not config.enabled:
                    continue
                if tool.name.startswith(f"{name}_") or f"_{name}_" in tool.name:
                    for tag in config.tags:
                        if tag not in self._tools_by_tag:
                            self._tools_by_tag[tag] = []
                        if tool not in self._tools_by_tag[tag]:
                            self._tools_by_tag[tag].append(tool)
                    break

    async def get_tools(
        self,
        tags: Optional[List[str]] = None,
    ) -> List[BaseTool]:
        """
        获取 MCP 工具

        Args:
            tags: 要获取的工具标签列表，如 ["lark", "github"]
                  如果为 None 或空列表，返回所有工具

        Returns:
            BaseTool 列表
        """
        if not self._initialized:
            await self.initialize()

        if not self._tools:
            return []

        if not tags:
            logger.info(f"获取所有工具{self._tools}")
            return self._tools

        result: List[BaseTool] = []
        seen = set()
        for tag in tags:
            if tag in self._tools_by_tag:
                for tool in self._tools_by_tag[tag]:
                    if id(tool) not in seen:
                        result.append(tool)
                        seen.add(id(tool))
        logger.info(f"获取工具{result}")
        return result

    def get_available_tags(self) -> List[str]:
        """获取所有可用的工具标签"""
        if not self._tools_by_tag:
            return []
        return list(self._tools_by_tag.keys())

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized

    async def close(self) -> None:
        """关闭 MCP 客户端"""
        if self._client:
            try:
                await self._client.aclose()
                logger.info("MCP 客户端已关闭")
            except Exception as e:
                logger.warning("关闭 MCP 客户端失败", error=str(e))
            finally:
                self._client = None
                self._tools = None
                self._tools_by_tag = None
                self._initialized = False


_mcp_manager: Optional[MCPServiceManager] = None


def get_mcp_manager() -> MCPServiceManager:
    """获取 MCP 服务管理器单例"""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPServiceManager()
    return _mcp_manager


async def initialize_mcp() -> None:
    """初始化 MCP 服务（应用启动时调用）"""
    manager = get_mcp_manager()
    await manager.initialize()
