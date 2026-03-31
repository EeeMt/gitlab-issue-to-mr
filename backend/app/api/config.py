"""Configuration API endpoints - aggregates all config submodules."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_effective_settings, get_settings
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.runtime_config import (
    load_runtime_config_from_db,
    reset_all_runtime_config_overrides,
    reset_runtime_config_override,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Import config submodules
from app.api import config_integration, config_runtime

# Import section models for Pydantic model definitions
from app.api.config_runtime import RuntimeConfigSection, RuntimeConfigUpdate
from app.api.config_integration import IntegrationConfigSection, IntegrationConfigUpdate


class AuthConfigSection(BaseModel):
    """Auth settings in the config response."""
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


class AuthConfigUpdate(BaseModel):
    """Request model for updating auth settings."""
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


class ConfigResponse(BaseModel):
    """Full configuration response combining all config sections."""
    runtime: "RuntimeConfigSection"
    auth: AuthConfigSection
    integration: "IntegrationConfigSection"


class ConfigUpdate(BaseModel):
    """Request model for updating all config sections."""
    runtime: Optional[RuntimeConfigUpdate] = None
    auth: Optional[AuthConfigUpdate] = None
    integration: Optional[IntegrationConfigUpdate] = None


def _serialize_auth_config(settings: Settings) -> AuthConfigSection:
    return AuthConfigSection(
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
    )


def _serialize_effective_config() -> ConfigResponse:
    settings = get_effective_settings()
    return ConfigResponse(
        runtime=config_runtime._serialize_runtime_config(settings),
        auth=_serialize_auth_config(settings),
        integration=config_integration._serialize_integration_config(settings),
    )


def _validate_oidc_ready(settings: Settings) -> None:
    """Validate that OIDC has all required fields configured."""
    from fastapi import HTTPException, status
    missing = []
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


@router.get("/config")
async def get_config(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Get current configuration (all sections)."""
    await load_runtime_config_from_db(db)
    return _serialize_effective_config()


@router.patch("/config")
async def update_config(
    config_update: ConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Update persisted configuration overrides (all sections)."""
    await load_runtime_config_from_db(db)

    # Handle runtime updates via config_runtime
    if config_update.runtime:
        from app.api.config_runtime import _normalize_runtime_updates, _build_preview_settings
        runtime_updates = _normalize_runtime_updates(
            config_update.runtime.model_dump(exclude_unset=True)
        )
        clear_alert_webhook = bool(runtime_updates.pop("clear_alert_webhook_url", False))
        clear_anthropic_api_key = bool(runtime_updates.pop("clear_anthropic_api_key", False))
        preview_settings = _build_preview_settings(runtime_updates, get_settings())

        if clear_alert_webhook and "alert_webhook_url" not in runtime_updates:
            runtime_updates["alert_webhook_url"] = get_settings().alert_webhook_url
        if clear_anthropic_api_key and "anthropic_api_key" not in runtime_updates:
            runtime_updates["anthropic_api_key"] = get_settings().anthropic_api_key

        from app.core.config_crypto import ConfigEncryptionError
        from app.runtime_config import save_runtime_config_override, reset_runtime_config_override
        try:
            for key, value in runtime_updates.items():
                await save_runtime_config_override(db, key, value)
                logger.info("Updated config %s", key)

            if clear_alert_webhook and "alert_webhook_url" not in runtime_updates:
                await reset_runtime_config_override(db, "alert_webhook_url")
                logger.info("Cleared stored alert webhook URL")

            if clear_anthropic_api_key and "anthropic_api_key" not in runtime_updates:
                await reset_runtime_config_override(db, "anthropic_api_key")
                logger.info("Cleared stored Anthropic API key")
        except ConfigEncryptionError as exc:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    # Handle auth updates
    if config_update.auth:
        from app.api.oidc import _normalize_updates as _normalize_auth_updates
        auth_updates = _normalize_auth_updates(
            config_update.auth.model_dump(exclude_unset=True)
        )
        auth_updates.pop("clear_oidc_client_secret", None)
        clear_secret = bool(config_update.auth.clear_oidc_client_secret)

        if auth_updates or clear_secret:
            from app.api.oidc import _build_preview_settings as _build_auth_preview
            from app.core.config_crypto import ConfigEncryptionError
            from app.runtime_config import save_runtime_config_override, reset_runtime_config_override
            preview_settings = _build_auth_preview(auth_updates)
            if preview_settings.oidc_enabled:
                _validate_oidc_ready(preview_settings)

            try:
                for key, value in auth_updates.items():
                    await save_runtime_config_override(db, key, value)
                    logger.info("Updated auth config %s", key)

                if clear_secret and "oidc_client_secret" not in auth_updates:
                    await reset_runtime_config_override(db, "oidc_client_secret")
                    logger.info("Cleared stored OIDC client secret")
            except ConfigEncryptionError as exc:
                from fastapi import HTTPException, status
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    # Handle integration updates via config_integration
    if config_update.integration:
        from app.api.config_integration import _normalize_integration_updates
        integration_updates = _normalize_integration_updates(
            config_update.integration.model_dump(exclude_unset=True)
        )
        clear_gitlab_bot_token = bool(integration_updates.pop("clear_gitlab_bot_token", False))
        clear_gitlab_admin_token = bool(integration_updates.pop("clear_gitlab_admin_token", False))
        clear_gitlab_webhook_secret = bool(integration_updates.pop("clear_gitlab_webhook_secret", False))

        if integration_updates or clear_gitlab_bot_token or clear_gitlab_admin_token or clear_gitlab_webhook_secret:
            from app.api.config_integration import _build_preview_settings_with_integration
            from app.core.config_crypto import ConfigEncryptionError
            from app.runtime_config import save_runtime_config_override, reset_runtime_config_override
            preview_settings = _build_preview_settings_with_integration(
                integration_updates, get_settings()
            )

            try:
                for key, value in integration_updates.items():
                    await save_runtime_config_override(db, key, value)
                    logger.info("Updated integration config %s", key)

                if clear_gitlab_bot_token and "gitlab_bot_token" not in integration_updates:
                    await reset_runtime_config_override(db, "gitlab_bot_token")
                    logger.info("Cleared stored GitLab bot token")

                if clear_gitlab_admin_token and "gitlab_admin_token" not in integration_updates:
                    await reset_runtime_config_override(db, "gitlab_admin_token")
                    logger.info("Cleared stored GitLab admin token")

                if clear_gitlab_webhook_secret and "gitlab_webhook_secret" not in integration_updates:
                    await reset_runtime_config_override(db, "gitlab_webhook_secret")
                    logger.info("Cleared stored GitLab webhook secret")
            except ConfigEncryptionError as exc:
                from fastapi import HTTPException, status
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    await load_runtime_config_from_db(db)
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
