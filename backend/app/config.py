"""Application configuration management."""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

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
    "mattermost_server_url": str,
    "mattermost_bot_token": str,
    "anthropic_base_url": str,
    "anthropic_api_key": str,
    "maven_cache_host_path": str,
    "maven_settings_host_path": str,
    "anthropic_model": str,
    "claude_max_turns": int,
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
    "session_retention_days": int,
    "cookie_secure": bool,
    "cookie_samesite": str,
    "auth_admin_usernames": str,
    "auth_admin_gitlab_groups": str,
    "worker_volume_mounts": str,  # JSON array of {host_path, container_path, mode}
    "worker_ca_cert_host_path": str,  # Absolute path to CA cert on Docker host; auto-added to volume mounts
    "worker_workspace_host_path": str,
    "worker_workspace_retention_days": int,
    "worker_failed_workspace_retention_days": int,
    "slot_max_tasks": int,  # Max tasks per 1-hour slot (0 = unlimited)
    "slot_max_tasks_enforce": bool,  # Enforce slot limit (True = hard reject, False = soft warning)
    "session_storage_root": str,
    "announcement_enabled": bool,
    "announcement_text": str,
    "announcement_level": str,  # "info" | "warning" | "error" | "success"
}

SECRET_CONFIG_KEYS = {
    "oidc_client_secret",
    "gitlab_bot_token",
    "gitlab_admin_token",
    "gitlab_webhook_secret",
    "alert_webhook_url",
    "mattermost_bot_token",
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
    claude_max_turns: int = Field(default=20)

    # Database Configuration - require via env var
    database_url: str = Field(default="postgresql+asyncpg://codify:codify_password@localhost:5432/codify")

    # Docker Engine HTTP API Configuration
    docker_host: str = Field(default="tcp://localhost:2376")
    docker_tls_ca: Optional[str] = Field(default=None)
    docker_tls_cert: Optional[str] = Field(default=None)
    docker_tls_key: Optional[str] = Field(default=None)

    # SSL/TLS Configuration
    # Path to a PEM-format CA certificate bundle for verifying HTTPS connections
    # to GitLab, Mattermost, Anthropic API, etc. Leave empty to use the system
    # CA store. In Docker deployments, mount the cert file and set the path here.
    custom_ca_bundle: Optional[str] = Field(default=None)

    # Application Configuration
    secret_key: str = Field(default="change-me-in-production")
    session_secret: str = Field(default="change-me-in-production")
    config_encryption_key: str = Field(default="")
    log_level: str = Field(default="INFO")
    backend_url: str = Field(default="http://localhost:8000")  # Backend API URL (used for webhook endpoint)
    frontend_url: str = Field(default="")  # Dashboard URL for task links; falls back to backend_url if empty

    @property
    def dashboard_url(self) -> str:
        """URL used for task links in GitLab comments. Uses frontend_url when set."""
        return self.frontend_url.strip() or self.backend_url
    auto_migrate: bool = Field(default=True)  # Auto-run migrations on startup

    # OIDC Authentication
    oidc_enabled: bool = Field(default=False)
    oidc_issuer_url: str = Field(default="")
    oidc_client_id: str = Field(default="")
    oidc_client_secret: str = Field(default="")
    oidc_redirect_uri: str = Field(default="")
    session_cookie_name: str = Field(default="codify_session")
    session_ttl_seconds: int = Field(default=28800)
    session_retention_days: int = Field(default=30)
    cookie_secure: bool = Field(default=True)
    cookie_samesite: str = Field(default="lax")
    auth_admin_usernames: str = Field(default="")
    auth_admin_gitlab_groups: str = Field(default="")
    auth_break_glass_enabled: bool = Field(default=False)
    auth_break_glass_username: str = Field(default="")
    auth_break_glass_password_hash: str = Field(default="")

    # Worker Configuration
    worker_image: str = Field(default="codify-worker:latest")
    worker_network: str = Field(default="bridge")  # Docker network for worker containers
    worker_container_prefix: str = Field(default="codify")  # Prefix for worker container names
    worker_skip_image_pull: bool = Field(default=False)  # Skip pull_image for local/test environments
    maven_cache_host_path: str = Field(default="")  # Host path to .m2/repository dir; empty = disabled
    maven_settings_host_path: str = Field(default="")  # Host path to settings.xml; empty = disabled
    # JSON array of volume mounts: [{"host_path": "/path", "container_path": "/path", "mode": "ro"}]
    worker_volume_mounts: str = Field(default="")
    # Shortcut: absolute path to CA cert on Docker host → automatically mounted into workers.
    # Simpler alternative to encoding a full JSON entry in worker_volume_mounts.
    worker_ca_cert_host_path: str = Field(default="")
    worker_workspace_host_path: str = Field(default="/opt/codify-workspaces")
    worker_workspace_retention_days: int = Field(default=14)
    worker_failed_workspace_retention_days: int = Field(default=30)

    # Session storage for Claude session persistence (Issue→Task model)
    session_storage_root: str = Field(default="/var/codify/sessions")

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
    mattermost_server_url: str = Field(default="")
    mattermost_bot_token: str = Field(default="")

    # Retry Configuration
    max_retries: int = Field(default=0)  # Max retry attempts for failed tasks
    retry_delay: int = Field(default=60)  # Delay between retries in seconds

    # Slot Capacity Configuration
    slot_max_tasks: int = Field(default=0)  # Max tasks per 1-hour slot (0 = unlimited)
    slot_max_tasks_enforce: bool = Field(default=False)  # True = hard reject, False = soft warning

    # Announcement Configuration
    announcement_enabled: bool = Field(default=False)
    announcement_text: str = Field(default="")
    announcement_level: str = Field(default="info")

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

    @property
    def worker_volume_mounts_parsed(self) -> list[dict]:
        """Parse worker_volume_mounts JSON string into a list of mount dicts.

        Also appends a CA cert mount when worker_ca_cert_host_path is set,
        so callers don't need to encode the full JSON for the common case.
        """
        mounts: list[dict] = []
        if self.worker_volume_mounts:
            try:
                parsed = json.loads(self.worker_volume_mounts)
                if isinstance(parsed, list):
                    mounts = parsed
            except json.JSONDecodeError:
                logger.warning("worker_volume_mounts is not valid JSON — ignoring custom mounts")
        if self.worker_ca_cert_host_path:
            mounts = [m for m in mounts if m.get("container_path") != "/etc/ssl/certs/custom-ca.crt"]
            mounts.append(
                {
                    "host_path": self.worker_ca_cert_host_path,
                    "container_path": "/etc/ssl/certs/custom-ca.crt",
                    "mode": "ro",
                }
            )
        return mounts


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
