"""全局配置管理，支持切换 Java 模型网关、公共 OpenAI 兼容 API 与本地 Mock 模式。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """应用配置项，自动从环境变量及 .env 文件加载。"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LogOps-Agent"
    app_version: str = "0.1.0"
    debug: bool = False

    # 模型网关与提供方
    llm_provider: Literal["gateway", "openai", "mock"] = "mock"
    gateway_base_url: str = "http://localhost:8080/v1"
    gateway_api_key: str = "sk-gateway-local-dev"
    gateway_model: str = "gpt-4o-mini"
    gateway_embedding_model: str = "text-embedding-3-small"

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    gateway_timeout_seconds: float = 30.0
    gateway_max_retries: int = 3
    gateway_backoff_base: float = 0.5
    gateway_backoff_max: float = 8.0
    allow_mock_fallback: bool = True

    # 知识库与数据目录
    knowledge_dir: Path = PROJECT_ROOT / "data" / "knowledge"
    mock_logs_dir: Path = PROJECT_ROOT / "data" / "mock_logs"
    mock_source_dir: Path = PROJECT_ROOT / "data" / "mock_source"

    # RAG & Qdrant 配置
    qdrant_mode: Literal["memory", "local"] = "memory"
    qdrant_path: Path = PROJECT_ROOT / "data" / "qdrant_local"
    qdrant_collection: str = "logops_knowledge"
    embedding_backend: Literal["local", "gateway"] = "local"
    embedding_dim: int = 256

    # Agent 状态机配置
    agent_max_steps: int = 8
    agent_token_budget: int = 6000
    agent_relevance_threshold: float = 0.45

    def active_base_url(self) -> str:
        """返回当前生效的 OpenAI 兼容接口 Base URL。"""
        if self.llm_provider == "openai":
            return self.openai_base_url.rstrip("/")
        return self.gateway_base_url.rstrip("/")

    def active_api_key(self) -> str:
        """返回当前生效的 API Key。"""
        if self.llm_provider == "openai":
            return self.openai_api_key
        return self.gateway_api_key

    def active_model(self) -> str:
        """返回当前生效的模型名称。"""
        if self.llm_provider == "openai":
            return self.openai_model
        return self.gateway_model


@lru_cache
def get_settings() -> Settings:
    """获取全局单例配置。"""
    return Settings()
