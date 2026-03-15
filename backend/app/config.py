"""Application configuration management."""

from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RuntimeConfigValue = Union[int, str, bool]

PERSISTED_CONFIG_TYPES: dict[str, type[RuntimeConfigValue]] = {
    "gitlab_url": str,
    "gitlab_bot_token": str,
    "gitlab_admin_token": str,
    "gitlab_webhook_secret": str,
    "max_concurrency": int,
    "task_timeout": int,
    "scheduler_interval": int,
    "default_target_branch": str,
    "max_retries": int,
    "retry_delay": int,
    "alert_on_failure": bool,
    "alert_webhook_url": str,
    "anthropic_base_url": str,
    "anthropic_api_key": str,
    "anthropic_model": str,
    "allow_monitor_for_users": bool,
    "allow_schedule_overview_for_users": bool,
    "allow_analytics_for_users": bool,
    "allow_oidc_diagnostics_for_users": bool,
    "oidc_enabled": bool,
    "oidc_issuer_url": str,
    "oidc_client_id": str,
    "oidc_client_secret": str,
    "oidc_redirect_uri": str,
    "session_cookie_name": str,
    "session_ttl_seconds": int,
    "cookie_secure": bool,
    "cookie_samesite": str,
    "auth_admin_usernames": str,
    "auth_admin_gitlab_groups": str,
}

SECRET_CONFIG_KEYS = {
    "oidc_client_secret",
    "gitlab_bot_token",
    "gitlab_admin_token",
    "gitlab_webhook_secret",
    "alert_webhook_url",
    "anthropic_api_key",
}


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
    gitlab_admin_token: str = Field(default="")
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
    session_secret: str = Field(default="change-me-in-production")
    config_encryption_key: str = Field(default="")
    log_level: str = Field(default="INFO")
    backend_url: str = Field(default="http://localhost:8000")  # Frontend/Backend URL for links
    auto_migrate: bool = Field(default=True)  # Auto-run migrations on startup

    # OIDC Authentication
    oidc_enabled: bool = Field(default=False)
    oidc_issuer_url: str = Field(default="")
    oidc_client_id: str = Field(default="")
    oidc_client_secret: str = Field(default="")
    oidc_redirect_uri: str = Field(default="")
    session_cookie_name: str = Field(default="gimr_session")
    session_ttl_seconds: int = Field(default=28800)
    cookie_secure: bool = Field(default=True)
    cookie_samesite: str = Field(default="lax")
    auth_admin_usernames: str = Field(default="")
    auth_admin_gitlab_groups: str = Field(default="")
    auth_break_glass_enabled: bool = Field(default=False)
    auth_break_glass_username: str = Field(default="")
    auth_break_glass_password_hash: str = Field(default="")

    # Worker Configuration
    worker_image: str = Field(default="gitlab-issues-to-mr-worker:latest")
    maven_cache_host_path: str = Field(default="")  # Host path to .m2/repository dir; empty = disabled
    maven_settings_host_path: str = Field(default="")  # Host path to settings.xml; empty = disabled

    # Scheduler Configuration
    max_concurrency: int = Field(default=3)
    task_timeout: int = Field(default=1800)  # 30 minutes
    scheduler_interval: int = Field(default=5)  # seconds
    default_target_branch: str = Field(default="main")
    allow_monitor_for_users: bool = Field(default=False)
    allow_schedule_overview_for_users: bool = Field(default=False)
    allow_analytics_for_users: bool = Field(default=False)
    allow_oidc_diagnostics_for_users: bool = Field(default=False)

    # Alert Configuration
    alert_webhook_url: Optional[str] = Field(default=None)  # Slack/Discord webhook URL
    alert_on_failure: bool = Field(default=False)  # Send alert when task fails

    # Retry Configuration
    max_retries: int = Field(default=0)  # Max retry attempts for failed tasks
    retry_delay: int = Field(default=60)  # Delay between retries in seconds

    @property
    def project_root(self) -> Path:
        """Get the absolute path to the project root directory."""
        return Path(__file__).parent.parent.parent

    @property
    def admin_usernames(self) -> set[str]:
        return {item.strip() for item in self.auth_admin_usernames.split(",") if item.strip()}

    @property
    def admin_gitlab_groups(self) -> set[str]:
        return {item.strip() for item in self.auth_admin_gitlab_groups.split(",") if item.strip()}

    @property
    def break_glass_enabled(self) -> bool:
        return (
            self.auth_break_glass_enabled
            and bool(self.auth_break_glass_username.strip())
            and bool(self.auth_break_glass_password_hash.strip())
        )


@lru_cache
def get_settings() -> Settings:
    """Get settings instance."""
    return Settings()


# Persisted configuration overrides loaded from the database into each process.
_runtime_config: dict[str, RuntimeConfigValue] = {}


def get_runtime_config() -> dict[str, RuntimeConfigValue]:
    """Get persisted configuration overrides."""
    return _runtime_config.copy()


def get_runtime_config_types() -> dict[str, type[RuntimeConfigValue]]:
    """Get supported persisted configuration keys and their types."""
    return PERSISTED_CONFIG_TYPES.copy()


def get_secret_config_keys() -> set[str]:
    """Get config keys that should be encrypted at rest."""
    return set(SECRET_CONFIG_KEYS)


def set_runtime_config(overrides: dict[str, RuntimeConfigValue]) -> None:
    """Replace in-memory runtime configuration overrides."""
    _runtime_config.clear()
    _runtime_config.update(overrides)


def update_runtime_config(key: str, value: RuntimeConfigValue) -> None:
    """Update persisted configuration override."""
    if key not in PERSISTED_CONFIG_TYPES:
        raise KeyError(f"Unknown runtime config key: {key}")
    _runtime_config[key] = value


def reset_runtime_config(key: Optional[str] = None) -> None:
    """Reset one or all runtime configuration overrides."""
    if key is None:
        _runtime_config.clear()
        return

    _runtime_config.pop(key, None)


def get_effective_settings() -> Settings:
    """Get effective settings with runtime overrides applied."""
    settings = get_settings()
    settings_data = settings.model_dump()
    settings_data.update(_runtime_config)
    return Settings(**settings_data)
