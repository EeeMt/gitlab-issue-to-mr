"""Application configuration management."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # GitLab Configuration
    gitlab_url: str = Field(default="https://gitlab.example.com")
    gitlab_bot_token: str = Field(default="")
    gitlab_webhook_secret: str = Field(default="")

    # Claude CLI Configuration (passed to Worker)
    anthropic_base_url: str = Field(default="http://localhost:11434/v1")
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514")

    # Database Configuration - require via env var
    database_url: str = Field(default="postgresql+asyncpg://gimr:gimr_password@localhost:5432/gimr")

    # Docker Engine HTTP API Configuration
    docker_host: str = Field(default="tcp://localhost:2376")
    docker_tls_ca: Optional[str] = Field(default=None)
    docker_tls_cert: Optional[str] = Field(default=None)
    docker_tls_key: Optional[str] = Field(default=None)

    # Application Configuration
    secret_key: str = Field(default="change-me-in-production")
    log_level: str = Field(default="INFO")

    # Worker Configuration
    worker_image: str = Field(default="gitlab-issues-to-mr-worker:latest")

    # Scheduler Configuration
    max_concurrency: int = Field(default=3)
    task_timeout: int = Field(default=1800)  # 30 minutes
    scheduler_interval: int = Field(default=5)  # seconds
    default_target_branch: str = Field(default="main")

    # Get absolute path for the project root
    @property
    def project_root(self) -> Path:
        """Get the absolute path to the project root directory."""
        return Path(__file__).parent.parent.parent


def get_settings() -> Settings:
    """Get settings instance."""
    return Settings()
