"""Configuration API endpoints."""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from gitlab.exceptions import GitlabError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_effective_settings, get_runtime_config_types, get_settings
from app.core.config_crypto import ConfigEncryptionError
from app.core.gitlab_client import GitLabClient
from app.core.oidc import (
    OIDCConfigurationError,
    build_authorization_url_for_settings,
    get_required_oidc_scope_string,
    get_required_oidc_scopes,
    get_oidc_discovery_document_for_settings,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user, require_page_access
from app.project_webhook_config import get_project_webhook_secret, has_project_webhook_secret, save_project_webhook_secret
from app.runtime_config import (
    load_runtime_config_from_db,
    reset_all_runtime_config_overrides,
    reset_runtime_config_override,
    save_runtime_config_override,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class RuntimeConfigSection(BaseModel):
    max_concurrency: int
    task_timeout: int
    scheduler_interval: int
    default_target_branch: str
    max_retries: int
    retry_delay: int
    alert_on_failure: bool
    alert_webhook_url_configured: bool
    anthropic_base_url: str
    anthropic_api_key_configured: bool
    anthropic_model: str
    claude_max_turns: int
    allow_monitor_for_users: bool
    allow_schedule_overview_for_users: bool
    allow_analytics_for_users: bool
    allow_oidc_diagnostics_for_users: bool


class AuthConfigSection(BaseModel):
    oidc_enabled: bool
    oidc_issuer_url: str
    oidc_client_id: str
    oidc_redirect_uri: str
    session_cookie_name: str
    session_ttl_seconds: int
    cookie_secure: bool
    cookie_samesite: str
    auth_admin_usernames: str
    auth_admin_gitlab_groups: str
    oidc_client_secret_configured: bool


class IntegrationConfigSection(BaseModel):
    gitlab_url: str
    gitlab_bot_token_configured: bool
    gitlab_admin_token_configured: bool
    gitlab_webhook_secret_configured: bool


class ConfigResponse(BaseModel):
    runtime: RuntimeConfigSection
    auth: AuthConfigSection
    integration: IntegrationConfigSection


class RuntimeConfigUpdate(BaseModel):
    max_concurrency: Optional[int] = None
    task_timeout: Optional[int] = None
    scheduler_interval: Optional[int] = None
    default_target_branch: Optional[str] = None
    max_retries: Optional[int] = None
    retry_delay: Optional[int] = None
    alert_on_failure: Optional[bool] = None
    alert_webhook_url: Optional[str] = None
    clear_alert_webhook_url: bool = False
    anthropic_base_url: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    clear_anthropic_api_key: bool = False
    anthropic_model: Optional[str] = None
    claude_max_turns: Optional[int] = None
    allow_monitor_for_users: Optional[bool] = None
    allow_schedule_overview_for_users: Optional[bool] = None
    allow_analytics_for_users: Optional[bool] = None
    allow_oidc_diagnostics_for_users: Optional[bool] = None


class AuthConfigUpdate(BaseModel):
    oidc_enabled: Optional[bool] = None
    oidc_issuer_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    clear_oidc_client_secret: bool = False
    oidc_redirect_uri: Optional[str] = None
    session_cookie_name: Optional[str] = None
    session_ttl_seconds: Optional[int] = None
    cookie_secure: Optional[bool] = None
    cookie_samesite: Optional[str] = None
    auth_admin_usernames: Optional[str] = None
    auth_admin_gitlab_groups: Optional[str] = None


class IntegrationConfigUpdate(BaseModel):
    gitlab_url: Optional[str] = None
    gitlab_bot_token: Optional[str] = None
    clear_gitlab_bot_token: bool = False
    gitlab_admin_token: Optional[str] = None
    clear_gitlab_admin_token: bool = False
    gitlab_webhook_secret: Optional[str] = None
    clear_gitlab_webhook_secret: bool = False


class ConfigUpdate(BaseModel):
    runtime: Optional[RuntimeConfigUpdate] = None
    auth: Optional[AuthConfigUpdate] = None
    integration: Optional[IntegrationConfigUpdate] = None


class OIDCConfigTestRequest(BaseModel):
    auth: AuthConfigUpdate


class OIDCConfigTestResponse(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    authorization_url_preview: str
    required_scopes: list[str]
    warnings: list[str]


class GitLabConfigTestRequest(BaseModel):
    integration: IntegrationConfigUpdate


class GitLabConfigTestResponse(BaseModel):
    server_version: str
    username: str
    gitlab_url: str


class GitLabProjectWebhookSetupResponse(BaseModel):
    action: str
    project_id: int
    project_name: str
    project_path_with_namespace: str
    webhook_url: str
    hook_id: int


class GitLabProjectWebhookStatusResponse(BaseModel):
    project_id: int
    project_name: str
    project_path_with_namespace: str
    target_webhook_url: str
    status: str
    status_detail: Optional[str] = None
    hook_found: bool
    hook_id: Optional[int] = None
    hook_url: Optional[str] = None
    note_events: Optional[bool] = None
    enable_ssl_verification: Optional[bool] = None
    managed_secret_configured: bool
    global_secret_fallback_configured: bool
    secret_mode: str


class OIDCDiagnosticsCheck(BaseModel):
    key: str
    label: str
    status: str
    detail: str


class OIDCDiagnosticsResponse(BaseModel):
    oidc_enabled: bool
    break_glass_enabled: bool
    issuer_url: str
    redirect_uri: str
    client_id_configured: bool
    client_secret_configured: bool
    session_cookie_name: str
    session_ttl_seconds: int
    cookie_secure: bool
    cookie_samesite: str
    required_scopes: list[str]
    required_scope_string: str
    authorization_url_preview: Optional[str]
    discovery_issuer: Optional[str]
    authorization_endpoint: Optional[str]
    token_endpoint: Optional[str]
    userinfo_endpoint: Optional[str]
    checks: list[OIDCDiagnosticsCheck]
    warnings: list[str]


def _serialize_effective_config() -> ConfigResponse:
    settings = get_effective_settings()
    return ConfigResponse(
        runtime=RuntimeConfigSection(
            max_concurrency=settings.max_concurrency,
            task_timeout=settings.task_timeout,
            scheduler_interval=settings.scheduler_interval,
            default_target_branch=settings.default_target_branch,
            max_retries=settings.max_retries,
            retry_delay=settings.retry_delay,
            alert_on_failure=settings.alert_on_failure,
            alert_webhook_url_configured=bool(settings.alert_webhook_url),
            anthropic_base_url=settings.anthropic_base_url,
            anthropic_api_key_configured=bool(settings.anthropic_api_key),
            anthropic_model=settings.anthropic_model,
            claude_max_turns=settings.claude_max_turns,
            allow_monitor_for_users=settings.allow_monitor_for_users,
            allow_schedule_overview_for_users=settings.allow_schedule_overview_for_users,
            allow_analytics_for_users=settings.allow_analytics_for_users,
            allow_oidc_diagnostics_for_users=settings.allow_oidc_diagnostics_for_users,
        ),
        auth=AuthConfigSection(
            oidc_enabled=settings.oidc_enabled,
            oidc_issuer_url=settings.oidc_issuer_url,
            oidc_client_id=settings.oidc_client_id,
            oidc_redirect_uri=settings.oidc_redirect_uri,
            session_cookie_name=settings.session_cookie_name,
            session_ttl_seconds=settings.session_ttl_seconds,
            cookie_secure=settings.cookie_secure,
            cookie_samesite=settings.cookie_samesite,
            auth_admin_usernames=settings.auth_admin_usernames,
            auth_admin_gitlab_groups=settings.auth_admin_gitlab_groups,
            oidc_client_secret_configured=bool(settings.oidc_client_secret),
        ),
        integration=IntegrationConfigSection(
            gitlab_url=settings.gitlab_url,
            gitlab_bot_token_configured=bool(settings.gitlab_bot_token),
            gitlab_admin_token_configured=bool(settings.gitlab_admin_token),
            gitlab_webhook_secret_configured=bool(settings.gitlab_webhook_secret),
        ),
    )


def _is_valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _sanitize_string_list(value: str) -> str:
    return ",".join(item.strip() for item in value.split(",") if item.strip())


def _build_gitlab_project_webhook_status_response(
    *,
    project_id: int,
    project_name: str,
    project_path_with_namespace: str,
    target_webhook_url: str,
    managed_secret_configured: bool,
    global_secret_fallback_configured: bool,
    matched_hook: Optional[dict[str, Any]] = None,
    inspection_error: Optional[str] = None,
) -> GitLabProjectWebhookStatusResponse:
    secret_mode = "project" if managed_secret_configured else "global_fallback" if global_secret_fallback_configured else "none"
    hook_found = matched_hook is not None
    note_events = bool(matched_hook.get("note_events")) if matched_hook is not None else None
    enable_ssl_verification = bool(matched_hook.get("enable_ssl_verification")) if matched_hook is not None else None

    if inspection_error:
        status_value = "error"
        status_detail = inspection_error
    elif not hook_found:
        status_value = "missing"
        status_detail = "No webhook matches the configured callback URL"
    elif note_events and enable_ssl_verification:
        status_value = "configured"
        status_detail = None
    else:
        status_value = "needs_attention"
        issues: list[str] = []
        if not note_events:
            issues.append("note events disabled")
        if not enable_ssl_verification:
            issues.append("SSL verification disabled")
        status_detail = ", ".join(issues) if issues else "Webhook settings need attention"

    return GitLabProjectWebhookStatusResponse(
        project_id=project_id,
        project_name=project_name,
        project_path_with_namespace=project_path_with_namespace,
        target_webhook_url=target_webhook_url,
        status=status_value,
        status_detail=status_detail,
        hook_found=hook_found,
        hook_id=int(matched_hook["id"]) if matched_hook is not None else None,
        hook_url=str(matched_hook.get("url", "")) if matched_hook is not None else None,
        note_events=note_events,
        enable_ssl_verification=enable_ssl_verification,
        managed_secret_configured=managed_secret_configured,
        global_secret_fallback_configured=global_secret_fallback_configured,
        secret_mode=secret_mode,
    )


def _build_preview_settings(overrides: dict[str, Any]) -> Settings:
    settings_data = get_effective_settings().model_dump()
    settings_data.update(overrides)
    return Settings(**settings_data)


def _validate_config_value(key: str, value: object) -> object:
    if key == "max_concurrency":
        if not isinstance(value, int) or value < 1 or value > 20:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="max_concurrency must be between 1 and 20",
            )
        return value

    if key == "task_timeout":
        if not isinstance(value, int) or value < 60 or value > 7200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="task_timeout must be between 60 and 7200 seconds",
            )
        return value

    if key == "scheduler_interval":
        if not isinstance(value, int) or value < 1 or value > 60:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="scheduler_interval must be between 1 and 60 seconds",
            )
        return value

    if key == "default_target_branch":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="default_target_branch cannot be empty",
            )
        return value.strip()

    if key == "gitlab_url":
        if not isinstance(value, str) or not value.strip() or not _is_valid_http_url(value.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="gitlab_url must be a valid http/https URL",
            )
        return value.strip()

    if key == "gitlab_bot_token":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="gitlab_bot_token cannot be empty",
            )
        return value.strip()

    if key == "gitlab_admin_token":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="gitlab_admin_token cannot be empty",
            )
        return value.strip()

    if key == "gitlab_webhook_secret":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="gitlab_webhook_secret cannot be empty",
            )
        return value.strip()

    if key == "max_retries":
        if not isinstance(value, int) or value < 0 or value > 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="max_retries must be between 0 and 10",
            )
        return value

    if key == "retry_delay":
        if not isinstance(value, int) or value < 1 or value > 3600:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="retry_delay must be between 1 and 3600 seconds",
            )
        return value

    if key in {"anthropic_base_url", "alert_webhook_url"}:
        if not isinstance(value, str) or not value.strip() or not _is_valid_http_url(value.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be a valid http/https URL",
            )
        return value.strip()

    if key == "anthropic_model":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="anthropic_model cannot be empty",
            )
        return value.strip()

    if key == "anthropic_api_key":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="anthropic_api_key cannot be empty",
            )
        return value.strip()

    if key == "claude_max_turns":
        if not isinstance(value, int) or value < 1 or value > 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="claude_max_turns must be between 1 and 1000",
            )
        return value

    if key in {"oidc_issuer_url", "oidc_redirect_uri"}:
        if not isinstance(value, str) or not value.strip() or not _is_valid_http_url(value.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be a valid http/https URL",
            )
        return value.strip()

    if key == "oidc_client_id":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="oidc_client_id cannot be empty",
            )
        return value.strip()

    if key == "oidc_client_secret":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="oidc_client_secret cannot be empty",
            )
        return value.strip()

    if key in {
        "oidc_enabled",
        "alert_on_failure",
        "allow_monitor_for_users",
        "allow_schedule_overview_for_users",
        "allow_analytics_for_users",
        "allow_oidc_diagnostics_for_users",
    }:
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be a boolean",
            )
        return value

    if key == "session_cookie_name":
        if not isinstance(value, str) or not value.strip() or " " in value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="session_cookie_name must be a non-empty token without spaces",
            )
        return value.strip()

    if key == "session_ttl_seconds":
        if not isinstance(value, int) or value < 300 or value > 604800:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="session_ttl_seconds must be between 300 and 604800 seconds",
            )
        return value

    if key == "cookie_secure":
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cookie_secure must be a boolean",
            )
        return value

    if key == "cookie_samesite":
        if not isinstance(value, str) or value.strip().lower() not in {"lax", "strict", "none"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cookie_samesite must be one of: lax, strict, none",
            )
        return value.strip().lower()

    if key in {"auth_admin_usernames", "auth_admin_gitlab_groups"}:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be a comma-separated string",
            )
        return _sanitize_string_list(value)

    return value


def _normalize_updates(raw_updates: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in raw_updates.items():
        if key in {
            "clear_oidc_client_secret",
            "clear_alert_webhook_url",
            "clear_anthropic_api_key",
            "clear_gitlab_bot_token",
            "clear_gitlab_admin_token",
            "clear_gitlab_webhook_secret",
        }:
            normalized[key] = bool(value)
            continue
        normalized[key] = _validate_config_value(key, value)
    return normalized


def _validate_oidc_ready(settings: Settings) -> None:
    missing: list[str] = []
    if not settings.oidc_issuer_url:
        missing.append("oidc_issuer_url")
    if not settings.oidc_client_id:
        missing.append("oidc_client_id")
    if not settings.oidc_redirect_uri:
        missing.append("oidc_redirect_uri")
    if not settings.oidc_client_secret:
        missing.append("oidc_client_secret")

    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OIDC cannot be enabled until these fields are configured: {', '.join(missing)}",
        )


def _build_oidc_diagnostics_warnings(settings: Settings) -> list[str]:
    warnings: list[str] = []

    if settings.oidc_redirect_uri:
        parsed = urlparse(settings.oidc_redirect_uri)
        if parsed.path != "/api/auth/callback":
            warnings.append("Redirect URI path should usually be /api/auth/callback.")
        if parsed.scheme == "http" and settings.cookie_secure:
            warnings.append(
                "COOKIE_SECURE=true with an http redirect URI may prevent session cookies during local testing."
            )
        if parsed.scheme == "https" and not settings.cookie_secure:
            warnings.append(
                "COOKIE_SECURE=false with an https redirect URI weakens cookie protection in production."
            )

    if settings.session_ttl_seconds > 86400:
        warnings.append("Session TTL is longer than 24 hours. Consider shortening it for tighter session control.")

    if settings.cookie_samesite == "none" and not settings.cookie_secure:
        warnings.append("SameSite=None without secure cookies is rejected by many browsers.")

    if not settings.break_glass_enabled:
        warnings.append("Break-glass recovery is currently disabled.")

    if settings.admin_gitlab_groups:
        warnings.append(
            "Group-based admin bootstrap is enabled. Verify GitLab OIDC returns groups in claims or userinfo; otherwise those admin grants will not apply."
        )

    return warnings


def _build_gitlab_webhook_target_url(settings: Settings) -> str:
    backend_url = settings.backend_url.strip()
    if not backend_url or not _is_valid_http_url(backend_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="backend_url must be configured as a valid http/https URL before setting up GitLab webhooks.",
        )
    return f"{backend_url.rstrip('/')}/api/webhook/gitlab"


def _validate_gitlab_webhook_ready(settings: Settings) -> str:
    missing: list[str] = []
    if not settings.gitlab_url.strip():
        missing.append("gitlab_url")
    if not settings.gitlab_admin_token.strip():
        missing.append("gitlab_admin_token")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitLab webhook setup requires these configured fields: {', '.join(missing)}",
        )
    return _build_gitlab_webhook_target_url(settings)


def _build_endpoint_checks(discovery: dict[str, Any]) -> list[OIDCDiagnosticsCheck]:
    checks: list[OIDCDiagnosticsCheck] = []
    for key, label in (
        ("authorization_endpoint", "Authorization endpoint"),
        ("token_endpoint", "Token endpoint"),
        ("userinfo_endpoint", "Userinfo endpoint"),
    ):
        endpoint = str(discovery.get(key, "")).strip()
        checks.append(
            OIDCDiagnosticsCheck(
                key=key,
                label=label,
                status="ok" if _is_valid_http_url(endpoint) else "error",
                detail=endpoint or f"{label} is missing from discovery metadata.",
            )
        )
    return checks


@router.get("/config")
async def get_config(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Get current configuration."""
    await load_runtime_config_from_db(db)
    return _serialize_effective_config()


@router.patch("/config")
async def update_config(
    config_update: ConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Update persisted configuration overrides."""
    await load_runtime_config_from_db(db)

    runtime_updates = _normalize_updates(
        config_update.runtime.model_dump(exclude_unset=True) if config_update.runtime else {}
    )
    auth_updates = _normalize_updates(
        config_update.auth.model_dump(exclude_unset=True) if config_update.auth else {}
    )
    integration_updates = _normalize_updates(
        config_update.integration.model_dump(exclude_unset=True) if config_update.integration else {}
    )

    clear_secret = bool(auth_updates.pop("clear_oidc_client_secret", False))
    clear_alert_webhook = bool(runtime_updates.pop("clear_alert_webhook_url", False))
    clear_anthropic_api_key = bool(runtime_updates.pop("clear_anthropic_api_key", False))
    clear_gitlab_bot_token = bool(integration_updates.pop("clear_gitlab_bot_token", False))
    clear_gitlab_admin_token = bool(integration_updates.pop("clear_gitlab_admin_token", False))
    clear_gitlab_webhook_secret = bool(integration_updates.pop("clear_gitlab_webhook_secret", False))
    preview_updates = {**runtime_updates, **auth_updates, **integration_updates}
    if clear_secret and "oidc_client_secret" not in auth_updates:
        preview_updates["oidc_client_secret"] = get_settings().oidc_client_secret
    if clear_alert_webhook and "alert_webhook_url" not in runtime_updates:
        preview_updates["alert_webhook_url"] = get_settings().alert_webhook_url
    if clear_anthropic_api_key and "anthropic_api_key" not in runtime_updates:
        preview_updates["anthropic_api_key"] = get_settings().anthropic_api_key
    if clear_gitlab_bot_token and "gitlab_bot_token" not in integration_updates:
        preview_updates["gitlab_bot_token"] = get_settings().gitlab_bot_token
    if clear_gitlab_admin_token and "gitlab_admin_token" not in integration_updates:
        preview_updates["gitlab_admin_token"] = get_settings().gitlab_admin_token
    if clear_gitlab_webhook_secret and "gitlab_webhook_secret" not in integration_updates:
        preview_updates["gitlab_webhook_secret"] = get_settings().gitlab_webhook_secret

    preview_settings = _build_preview_settings(preview_updates)
    if preview_settings.oidc_enabled:
        _validate_oidc_ready(preview_settings)

    try:
        for key, value in runtime_updates.items():
            await save_runtime_config_override(db, key, value)
            logger.info("Updated config %s", key)

        for key, value in auth_updates.items():
            await save_runtime_config_override(db, key, value)
            logger.info("Updated auth config %s", key)

        for key, value in integration_updates.items():
            await save_runtime_config_override(db, key, value)
            logger.info("Updated integration config %s", key)

        if clear_secret and "oidc_client_secret" not in auth_updates:
            await reset_runtime_config_override(db, "oidc_client_secret")
            logger.info("Cleared stored OIDC client secret")

        if clear_alert_webhook and "alert_webhook_url" not in runtime_updates:
            await reset_runtime_config_override(db, "alert_webhook_url")
            logger.info("Cleared stored alert webhook URL")

        if clear_anthropic_api_key and "anthropic_api_key" not in runtime_updates:
            await reset_runtime_config_override(db, "anthropic_api_key")
            logger.info("Cleared stored Anthropic API key")

        if clear_gitlab_bot_token and "gitlab_bot_token" not in integration_updates:
            await reset_runtime_config_override(db, "gitlab_bot_token")
            logger.info("Cleared stored GitLab bot token")

        if clear_gitlab_admin_token and "gitlab_admin_token" not in integration_updates:
            await reset_runtime_config_override(db, "gitlab_admin_token")
            logger.info("Cleared stored GitLab admin token")

        if clear_gitlab_webhook_secret and "gitlab_webhook_secret" not in integration_updates:
            await reset_runtime_config_override(db, "gitlab_webhook_secret")
            logger.info("Cleared stored GitLab webhook secret")

        await load_runtime_config_from_db(db)
    except ConfigEncryptionError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return _serialize_effective_config()


@router.post("/config/reset")
async def reset_config(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Reset all persisted configuration overrides back to env/default values."""
    await reset_all_runtime_config_overrides(db)
    await load_runtime_config_from_db(db)
    logger.info("Reset all persisted configuration overrides")
    return _serialize_effective_config()


@router.delete("/config/{key}")
async def reset_config_key(
    key: str,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Reset one persisted configuration override back to env/default value."""
    if key not in get_runtime_config_types():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown config key: {key}",
        )

    await reset_runtime_config_override(db, key)
    await load_runtime_config_from_db(db)
    logger.info("Reset persisted configuration override for %s", key)
    return _serialize_effective_config()


@router.post("/config/gitlab/test", response_model=GitLabConfigTestResponse)
async def test_gitlab_config(
    request: GitLabConfigTestRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Validate GitLab connectivity with current or unsaved integration values."""
    await load_runtime_config_from_db(db)
    integration_updates = _normalize_updates(request.integration.model_dump(exclude_unset=True))
    integration_updates.pop("clear_gitlab_bot_token", None)
    preview_settings = _build_preview_settings(integration_updates)

    if not preview_settings.gitlab_url.strip() or not preview_settings.gitlab_bot_token.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitLab URL and bot token must be configured before testing the connection.",
        )

    client = GitLabClient(settings=preview_settings)
    try:
        version_payload = await asyncio.to_thread(client.gl.http_get, "/version")
        user_payload = await asyncio.to_thread(client.gl.http_get, "/user")
    except (GitlabError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitLab config test failed: {exc}",
        ) from exc
    finally:
        client.close()

    return GitLabConfigTestResponse(
        server_version=str(version_payload.get("version", "")),
        username=str(user_payload.get("username", "")),
        gitlab_url=preview_settings.gitlab_url,
    )


@router.post("/config/gitlab/projects/{project_id}/webhook", response_model=GitLabProjectWebhookSetupResponse)
async def setup_gitlab_project_webhook(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Create or update the GitLab webhook for one project."""
    await load_runtime_config_from_db(db)
    settings = get_effective_settings()
    webhook_url = _validate_gitlab_webhook_ready(settings)
    managed_secret = await get_project_webhook_secret(db, project_id)
    if not managed_secret:
        managed_secret = secrets.token_urlsafe(32)
        await save_project_webhook_secret(db, project_id, managed_secret)

    client = GitLabClient(settings=settings, private_token=settings.gitlab_admin_token)
    try:
        project = await asyncio.to_thread(client.get_project, project_id)
        result = await asyncio.to_thread(
            client.ensure_project_webhook,
            project_id,
            webhook_url,
            managed_secret,
        )
    except (GitlabError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitLab webhook setup failed: {exc}",
        ) from exc
    finally:
        client.close()

    hook_payload = result["hook"]
    return GitLabProjectWebhookSetupResponse(
        action=str(result["action"]),
        project_id=project_id,
        project_name=str(getattr(project, "name", "") or ""),
        project_path_with_namespace=str(getattr(project, "path_with_namespace", "") or ""),
        webhook_url=str(hook_payload.get("url", webhook_url)),
        hook_id=int(hook_payload["id"]),
    )


@router.get("/config/gitlab/projects/{project_id}/webhook", response_model=GitLabProjectWebhookStatusResponse)
async def get_gitlab_project_webhook_status(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Inspect the GitLab webhook status for one project."""
    await load_runtime_config_from_db(db)
    settings = get_effective_settings()
    target_webhook_url = _validate_gitlab_webhook_ready(settings)

    client = GitLabClient(settings=settings, private_token=settings.gitlab_admin_token)
    try:
        project = await asyncio.to_thread(client.get_project, project_id)
        hooks = await asyncio.to_thread(client.get_project_hooks, project_id)
    except (GitlabError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitLab webhook status lookup failed: {exc}",
        ) from exc
    finally:
        client.close()

    normalized_target = GitLabClient._normalize_hook_url(target_webhook_url)
    matched_hook = next(
        (
            hook for hook in hooks
            if GitLabClient._normalize_hook_url(str(hook.get("url", ""))) == normalized_target
        ),
        None,
    )

    return _build_gitlab_project_webhook_status_response(
        project_id=project_id,
        project_name=str(getattr(project, "name", "") or ""),
        project_path_with_namespace=str(getattr(project, "path_with_namespace", "") or ""),
        target_webhook_url=target_webhook_url,
        matched_hook=matched_hook,
        managed_secret_configured=await has_project_webhook_secret(db, project_id),
        global_secret_fallback_configured=bool(settings.gitlab_webhook_secret.strip()),
    )


@router.get("/config/gitlab/webhooks", response_model=list[GitLabProjectWebhookStatusResponse])
async def list_gitlab_project_webhook_statuses(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Inspect GitLab webhook status across all manageable projects."""
    await load_runtime_config_from_db(db)
    settings = get_effective_settings()
    target_webhook_url = _validate_gitlab_webhook_ready(settings)

    client = GitLabClient(settings=settings, private_token=settings.gitlab_admin_token)

    def collect_project_snapshots() -> list[dict[str, Any]]:
        projects = sorted(
            client.get_projects(),
            key=lambda project: str(project.get("path_with_namespace", "") or project.get("name", "")).lower(),
        )
        normalized_target = GitLabClient._normalize_hook_url(target_webhook_url)
        snapshots: list[dict[str, Any]] = []

        for project in projects:
            project_id = int(project["id"])
            inspection_error: Optional[str] = None
            matched_hook: Optional[dict[str, Any]] = None

            try:
                hooks = client.get_project_hooks(project_id)
                matched_hook = next(
                    (
                        hook for hook in hooks
                        if GitLabClient._normalize_hook_url(str(hook.get("url", ""))) == normalized_target
                    ),
                    None,
                )
            except (GitlabError, httpx.HTTPError) as exc:
                inspection_error = str(exc)

            snapshots.append({
                "project_id": project_id,
                "project_name": str(project.get("name", "") or ""),
                "project_path_with_namespace": str(project.get("path_with_namespace", "") or ""),
                "matched_hook": matched_hook,
                "inspection_error": inspection_error,
            })

        return snapshots

    try:
        snapshots = await asyncio.to_thread(collect_project_snapshots)
    except (GitlabError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitLab webhook status lookup failed: {exc}",
        ) from exc
    finally:
        client.close()

    statuses: list[GitLabProjectWebhookStatusResponse] = []
    global_secret_fallback_configured = bool(settings.gitlab_webhook_secret.strip())

    for snapshot in snapshots:
        statuses.append(
            _build_gitlab_project_webhook_status_response(
                project_id=int(snapshot["project_id"]),
                project_name=str(snapshot["project_name"]),
                project_path_with_namespace=str(snapshot["project_path_with_namespace"]),
                target_webhook_url=target_webhook_url,
                matched_hook=snapshot["matched_hook"],
                inspection_error=snapshot["inspection_error"],
                managed_secret_configured=await has_project_webhook_secret(db, int(snapshot["project_id"])),
                global_secret_fallback_configured=global_secret_fallback_configured,
            )
        )

    return statuses


@router.post("/config/oidc/test")
async def test_oidc_config(
    request: OIDCConfigTestRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Validate OIDC connectivity with current or unsaved config values."""
    await load_runtime_config_from_db(db)
    auth_updates = _normalize_updates(request.auth.model_dump(exclude_unset=True))
    auth_updates.pop("clear_oidc_client_secret", None)
    preview_settings = _build_preview_settings(auth_updates)

    try:
        discovery = await get_oidc_discovery_document_for_settings(preview_settings)
        authorization_url = await build_authorization_url_for_settings(
            preview_settings,
            state="config-test-state",
            nonce="config-test-nonce",
        )
    except (OIDCConfigurationError, ConfigEncryptionError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OIDC config test failed: {exc}",
        ) from exc

    return OIDCConfigTestResponse(
        issuer=str(discovery.get("issuer", "")),
        authorization_endpoint=str(discovery.get("authorization_endpoint", "")),
        token_endpoint=str(discovery.get("token_endpoint", "")),
        userinfo_endpoint=str(discovery.get("userinfo_endpoint", "")),
        authorization_url_preview=authorization_url,
        required_scopes=list(get_required_oidc_scopes()),
        warnings=_build_oidc_diagnostics_warnings(preview_settings),
    )


@router.get("/config/oidc/diagnostics", response_model=OIDCDiagnosticsResponse)
async def get_oidc_diagnostics(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_page_access("oidc_diagnostics")),
):
    """Return a richer OIDC diagnostics snapshot for operators."""
    await load_runtime_config_from_db(db)
    settings = get_effective_settings()
    warnings = _build_oidc_diagnostics_warnings(settings)
    checks: list[OIDCDiagnosticsCheck] = []
    authorization_url_preview: Optional[str] = None
    discovery_issuer: Optional[str] = None
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    userinfo_endpoint: Optional[str] = None

    try:
        discovery = await get_oidc_discovery_document_for_settings(settings)
        discovery_issuer = str(discovery.get("issuer", "")) or None
        authorization_endpoint = str(discovery.get("authorization_endpoint", "")) or None
        token_endpoint = str(discovery.get("token_endpoint", "")) or None
        userinfo_endpoint = str(discovery.get("userinfo_endpoint", "")) or None
        checks.append(
            OIDCDiagnosticsCheck(
                key="discovery",
                label="OIDC discovery",
                status="ok",
                detail=f"Fetched discovery document from issuer {discovery_issuer or settings.oidc_issuer_url}.",
            )
        )
        checks.extend(_build_endpoint_checks(discovery))
    except OIDCConfigurationError as exc:
        checks.append(
            OIDCDiagnosticsCheck(
                key="discovery",
                label="OIDC discovery",
                status="error",
                detail=str(exc),
            )
        )
    except httpx.HTTPError as exc:
        checks.append(
            OIDCDiagnosticsCheck(
                key="discovery",
                label="OIDC discovery",
                status="error",
                detail=f"Failed to fetch discovery document: {exc}",
            )
        )

    if _is_valid_http_url(settings.oidc_redirect_uri):
        checks.append(
            OIDCDiagnosticsCheck(
                key="redirect_uri",
                label="Redirect URI",
                status="ok" if settings.oidc_redirect_uri.endswith("/api/auth/callback") else "warning",
                detail=settings.oidc_redirect_uri,
            )
        )
    else:
        checks.append(
            OIDCDiagnosticsCheck(
                key="redirect_uri",
                label="Redirect URI",
                status="error",
                detail="Redirect URI is missing or invalid.",
            )
        )

    checks.append(
        OIDCDiagnosticsCheck(
            key="scope",
            label="Required scopes",
            status="ok",
            detail=get_required_oidc_scope_string(),
        )
    )
    checks.append(
        OIDCDiagnosticsCheck(
            key="cookie_policy",
            label="Cookie policy",
            status="warning" if warnings else "ok",
            detail=(
                "; ".join(warnings)
                if warnings
                else f"Cookie policy looks consistent: secure={settings.cookie_secure}, samesite={settings.cookie_samesite}."
            ),
        )
    )

    try:
        authorization_url_preview = await build_authorization_url_for_settings(
            settings,
            state="diagnostics-state",
            nonce="diagnostics-nonce",
        )
    except (OIDCConfigurationError, httpx.HTTPError):
        authorization_url_preview = None

    return OIDCDiagnosticsResponse(
        oidc_enabled=settings.oidc_enabled,
        break_glass_enabled=settings.break_glass_enabled,
        issuer_url=settings.oidc_issuer_url,
        redirect_uri=settings.oidc_redirect_uri,
        client_id_configured=bool(settings.oidc_client_id),
        client_secret_configured=bool(settings.oidc_client_secret),
        session_cookie_name=settings.session_cookie_name,
        session_ttl_seconds=settings.session_ttl_seconds,
        cookie_secure=settings.cookie_secure,
        cookie_samesite=settings.cookie_samesite,
        required_scopes=list(get_required_oidc_scopes()),
        required_scope_string=get_required_oidc_scope_string(),
        authorization_url_preview=authorization_url_preview,
        discovery_issuer=discovery_issuer,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        userinfo_endpoint=userinfo_endpoint,
        checks=checks,
        warnings=warnings,
    )
