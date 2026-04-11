from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = Field(default="dev", description="运行环境")
    app_name: str = Field(default="ai-agent-engine", description="应用名称")
    app_version: str = Field(default="1.0.0", description="应用版本")
    debug: bool = Field(default=True, description="调试模式")

    server_host: str = Field(default="0.0.0.0", description="服务监听地址")
    server_port: int = Field(default=8000, description="服务监听端口")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent",
        description="数据库连接URL",
    )
    database_pool_size: int = Field(default=10, description="数据库连接池大小")
    database_max_overflow: int = Field(default=20, description="数据库连接池最大溢出")

    redis_url: str = Field(
        default="redis://localhost:6379/0", description="Redis连接URL"
    )

    rabbitmq_url: str = Field(
        default="amqp://guest:guest@localhost:5672/", description="RabbitMQ连接URL"
    )
    rabbitmq_exchange: str = Field(
        default="agent-engine", description="RabbitMQ Exchange名称"
    )
    rabbitmq_prefetch_count: int = Field(
        default=10, description="RabbitMQ消费者预取数量"
    )

    openai_api_key: str = Field(
        default="",
        description="OpenAI API Key - 生产环境必须设置",
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI API Base URL",
    )
    openai_embedding_model: str = Field(
        default="text-embedding-v3", description="Embedding模型名称"
    )
    openai_embedding_dims: int = Field(
        default=1024, description="Embedding向量维度"
    )

    agent_model_name: str = Field(
        default="gpt-4o-mini", description="Agent 默认使用的 LLM 模型名称"
    )

    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"], description="CORS 允许的源"
    )

    log_level: str = Field(default="INFO", description="日志级别")
    log_format: str = Field(default="json", description="日志格式")

    langchain_tracing_v2: bool = Field(default=False, description="是否启用LangChain追踪")
    langchain_api_key: Optional[str] = Field(default=None, description="LangChain API Key")
    langchain_project: str = Field(
        default="ai-agent-engine", description="LangChain项目名称"
    )

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not v or v == "sk-your-api-key-here":
            raise ValueError(
                "openai_api_key is required and must be a valid API key. "
                "Please set your OpenAI API key in the OPENAI_API_KEY environment variable."
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
