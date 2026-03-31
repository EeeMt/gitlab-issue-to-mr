"""Shared validation utilities for config API modules."""

from urllib.parse import urlparse


def _is_valid_http_url(value: str) -> bool:
    """Check if a string is a valid HTTP/HTTPS URL."""
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _sanitize_string_list(value: str) -> str:
    """Normalize a comma-separated string list by trimming whitespace and removing empty items."""
    return ",".join(item.strip() for item in value.split(",") if item.strip())


def _validate_config_value(key: str, value: object) -> object:
    """Validate a single configuration value (handles all sections)."""
    from fastapi import HTTPException, status

    # === Runtime config validation ===
    if key == "max_concurrency":
        if not isinstance(value, int) or value < 1 or value > 20:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="max_concurrency must be between 1 and 20")
        return value

    if key == "task_timeout":
        if not isinstance(value, int) or value < 60 or value > 7200:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="task_timeout must be between 60 and 7200 seconds")
        return value

    if key == "scheduler_interval":
        if not isinstance(value, int) or value < 1 or value > 60:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="scheduler_interval must be between 1 and 60 seconds")
        return value

    if key == "default_target_branch":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="default_target_branch cannot be empty")
        return value.strip()

    if key == "max_retries":
        if not isinstance(value, int) or value < 0 or value > 10:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="max_retries must be between 0 and 10")
        return value

    if key == "retry_delay":
        if not isinstance(value, int) or value < 1 or value > 3600:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="retry_delay must be between 1 and 3600 seconds")
        return value

    if key in {"anthropic_base_url", "alert_webhook_url"}:
        if not isinstance(value, str) or not value.strip() or not _is_valid_http_url(value.strip()):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{key} must be a valid http/https URL")
        return value.strip()

    if key == "anthropic_model":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="anthropic_model cannot be empty")
        return value.strip()

    if key == "anthropic_api_key":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="anthropic_api_key cannot be empty")
        return value.strip()

    if key == "claude_max_turns":
        if not isinstance(value, int) or value < 1 or value > 1000:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="claude_max_turns must be between 1 and 1000")
        return value

    if key in {"alert_on_failure", "allow_monitor_for_users", "allow_schedule_overview_for_users", "allow_analytics_for_users", "allow_oidc_diagnostics_for_users"}:
        if not isinstance(value, bool):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{key} must be a boolean")
        return value

    # === Integration (GitLab) validation ===
    if key == "gitlab_url":
        if not isinstance(value, str) or not value.strip() or not _is_valid_http_url(value.strip()):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="gitlab_url must be a valid http/https URL")
        return value.strip()

    if key == "gitlab_bot_token":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="gitlab_bot_token cannot be empty")
        return value.strip()

    if key == "gitlab_admin_token":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="gitlab_admin_token cannot be empty")
        return value.strip()

    if key == "gitlab_webhook_secret":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="gitlab_webhook_secret cannot be empty")
        return value.strip()

    # === Mattermost validation ===
    if key == "mattermost_server_url":
        if not isinstance(value, str) or not value.strip() or not _is_valid_http_url(value.strip()):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mattermost_server_url must be a valid http/https URL")
        return value.strip()

    if key == "mattermost_bot_token":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mattermost_bot_token cannot be empty")
        return value.strip()

    # === OIDC validation ===
    if key in {"oidc_issuer_url", "oidc_redirect_uri"}:
        if not isinstance(value, str) or not value.strip() or not _is_valid_http_url(value.strip()):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{key} must be a valid http/https URL")
        return value.strip()

    if key == "oidc_client_id":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="oidc_client_id cannot be empty")
        return value.strip()

    if key == "oidc_client_secret":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="oidc_client_secret cannot be empty")
        return value.strip()

    # === Session validation ===
    if key == "session_cookie_name":
        if not isinstance(value, str) or not value.strip() or " " in value.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="session_cookie_name must be a non-empty token without spaces")
        return value.strip()

    if key == "session_ttl_seconds":
        if not isinstance(value, int) or value < 300 or value > 604800:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="session_ttl_seconds must be between 300 and 604800 seconds")
        return value

    if key == "cookie_secure":
        if not isinstance(value, bool):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cookie_secure must be a boolean")
        return value

    if key == "cookie_samesite":
        if not isinstance(value, str) or value.strip().lower() not in {"lax", "strict", "none"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cookie_samesite must be one of: lax, strict, none")
        return value.strip().lower()

    if key in {"auth_admin_usernames", "auth_admin_gitlab_groups"}:
        if not isinstance(value, str):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{key} must be a comma-separated string")
        return _sanitize_string_list(value)

    return value


def _normalize_updates(raw_updates: dict) -> dict:
    """Normalize config updates (handles clear flags for all sections)."""
    normalized: dict = {}

    # Handle runtime clear flags
    for key in ("clear_alert_webhook_url", "clear_anthropic_api_key"):
        if key in raw_updates:
            normalized[key] = bool(raw_updates[key])

    # Handle integration clear flags
    for key in ("clear_gitlab_bot_token", "clear_gitlab_admin_token", "clear_gitlab_webhook_secret", "clear_mattermost_bot_token"):
        if key in raw_updates:
            normalized[key] = bool(raw_updates[key])

    # Handle auth clear flags
    if "clear_oidc_client_secret" in raw_updates:
        normalized["clear_oidc_client_secret"] = bool(raw_updates["clear_oidc_client_secret"])

    return normalized
