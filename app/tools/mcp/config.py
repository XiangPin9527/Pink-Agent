"""
MCP 配置加载器

支持从 YAML 文件加载 MCP 服务器配置（硬编码方式）
"""
import os
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field

import yaml

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MCPServerConfig:
    """单个 MCP 服务器配置"""
    name: str
    enabled: bool = True
    command: str = ""
    args: List[str] = field(default_factory=list)
    transport: str = "stdio"
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    env: Optional[Dict[str, str]] = None
    tags: Set[str] = field(default_factory=lambda: {"default"})


class MCPConfigLoader:
    """
    MCP 配置加载器

    从 YAML 文件加载 MCP 服务器配置
    """

    @classmethod
    def from_yaml(cls, path: str) -> Dict[str, MCPServerConfig]:
        """
        从 YAML 文件加载 MCP 服务器配置

        Args:
            path: YAML 文件路径

        Returns:
            服务器名称 -> MCPServerConfig 的映射
        """
        if not os.path.exists(path):
            logger.warning("MCP 配置文件不存在", path=path)
            return {}

        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not config or "mcp" not in config:
            logger.warning("MCP 配置文件格式错误或缺少 mcp 节点", path=path)
            return {}

        mcp_config = config.get("mcp", {})
        servers = {}

        for name, server_config in mcp_config.items():
            if not isinstance(server_config, dict):
                continue

            servers[name] = MCPServerConfig(
                name=name,
                enabled=server_config.get("enabled", True),
                command=server_config.get("command", ""),
                args=server_config.get("args", []),
                transport=server_config.get("transport", "stdio"),
                url=server_config.get("url"),
                headers=server_config.get("headers"),
                env=server_config.get("env"),
                tags=set(server_config.get("tags", ["default"])),
            )

            logger.debug(
                "加载 MCP 服务器配置",
                name=name,
                enabled=servers[name].enabled,
                command=servers[name].command,
            )

        logger.info("MCP 配置加载完成", server_count=len(servers))
        return servers

    @staticmethod
    def build_connection_config(server_config: MCPServerConfig) -> Dict[str, Any]:
        """
        将 MCPServerConfig 构建为 MultiServerMCPClient 所需的连接格式

        Args:
            server_config: MCP 服务器配置

        Returns:
            连接配置字典
        """
        conn_config: Dict[str, Any] = {
            "command": server_config.command,
            "args": server_config.args,
            "transport": server_config.transport,
        }

        if server_config.url:
            conn_config["url"] = server_config.url

        if server_config.headers:
            conn_config["headers"] = server_config.headers

        if server_config.env:
            conn_config["env"] = server_config.env

        return conn_config
