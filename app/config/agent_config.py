from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ClientType(str, Enum):
    DEFAULT = "DEFAULT"
    TASK_ANALYZER_CLIENT = "TASK_ANALYZER_CLIENT"
    PRECISION_EXECUTOR_CLIENT = "PRECISION_EXECUTOR_CLIENT"
    QUALITY_SUPERVISOR_CLIENT = "QUALITY_SUPERVISOR_CLIENT"


@dataclass
class PromptConfig:
    prompt_id: str
    prompt_name: str
    prompt_content: str


@dataclass
class AdvisorConfig:
    advisor_id: str
    advisor_type: str
    config: Dict = field(default_factory=dict)


@dataclass
class McpConfig:
    mcp_id: str
    mcp_name: str
    transport_type: str
    transport_config: Dict = field(default_factory=dict)
    request_timeout: int = 30000


@dataclass
class ClientConfig:
    client_id: str
    client_name: str
    description: str
    model_id: str
    prompt_ids: List[str] = field(default_factory=list)
    mcp_ids: List[str] = field(default_factory=list)
    advisor_ids: List[str] = field(default_factory=list)


@dataclass
class AgentFlowConfig:
    client_id: str
    client_name: str
    client_type: ClientType
    sequence: int


@dataclass
class AgentConfig:
    agent_id: str
    agent_name: str
    description: str
    flow_configs: List[AgentFlowConfig] = field(default_factory=list)
    clients: Dict[str, ClientConfig] = field(default_factory=dict)
    models: Dict[str, Dict] = field(default_factory=dict)
    apis: Dict[str, Dict] = field(default_factory=dict)
    prompts: Dict[str, PromptConfig] = field(default_factory=dict)
    advisors: Dict[str, AdvisorConfig] = field(default_factory=dict)
    mcps: Dict[str, McpConfig] = field(default_factory=dict)

    def get_client_by_type(self, client_type: ClientType) -> Optional[AgentFlowConfig]:
        for flow in self.flow_configs:
            if flow.client_type == client_type:
                return flow
        return None


_agent_configs: Dict[str, AgentConfig] = {}


def get_agent_config(agent_id: str) -> Optional[AgentConfig]:
    return _agent_configs.get(agent_id)


def register_agent_config(agent_id: str, config: AgentConfig) -> None:
    _agent_configs[agent_id] = config


def get_all_agent_configs() -> Dict[str, AgentConfig]:
    return _agent_configs.copy()
