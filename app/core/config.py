"""Core configuration for AI Log Analyzer."""

from functools import lru_cache
from typing import Any

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # API
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    api_workers: int = Field(default=4)

    # Database
    database_url: PostgresDsn

    # Ollama LLM
    ollama_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="mistral:latest")

    # Elasticsearch
    es_url: str
    es_index: str = Field(default="cluster-app_pcb-*")
    es_user: str | None = None
    es_password: str | None = None
    es_verify_certs: bool = Field(default=False)

    # Redis
    redis_url: str = Field(default="redis://localhost:6379")

    # Logging
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")

    # Security
    secret_key: str
    algorithm: str = Field(default="HS256")

    # Self-learning
    learning_enabled: bool = Field(default=True)
    auto_adjust_thresholds: bool = Field(default=True)
    min_samples_for_learning: int = Field(default=10)

    # Analysis
    max_context_tokens: int = Field(default=4000)
    llm_temperature: float = Field(default=0.1)
    llm_max_tokens: int = Field(default=1000)

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str | Any) -> str:
        """Validate and convert database URL."""
        if isinstance(v, str):
            return v
        return str(v)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

# Global settings instance
settings = get_settings()
