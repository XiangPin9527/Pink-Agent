from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ModelConfig:
    model_id: str
    model_name: str
    api_id: str
    temperature: float = 0.7
    max_tokens: int = 4096
    tool_mcp_ids: List[str] = field(default_factory=list)


@dataclass
class ApiConfig:
    api_id: str
    base_url: str
    api_key: str
    completion_path: str = "/v1/chat/completions"
    embeddings_path: str = "/v1/embeddings"


@dataclass
class LLMConfig:
    models: Dict[str, ModelConfig] = field(default_factory=dict)
    apis: Dict[str, ApiConfig] = field(default_factory=dict)
    default_model_id: Optional[str] = None

    def get_model(self, model_id: str) -> Optional[ModelConfig]:
        return self.models.get(model_id)

    def get_api(self, api_id: str) -> Optional[ApiConfig]:
        return self.apis.get(api_id)


_llm_config: Optional[LLMConfig] = None


def get_llm_config() -> LLMConfig:
    global _llm_config
    if _llm_config is None:
        _llm_config = LLMConfig()
    return _llm_config


def init_llm_config(config: LLMConfig) -> None:
    global _llm_config
    _llm_config = config
