"""Configuration API endpoints."""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_effective_settings, get_runtime_config_types, get_settings
from app.core.config_crypto import ConfigEncryptionError
from app.core.oidc import (
    OIDCConfigurationError,
    build_authorization_url_for_settings,
    get_oidc_discovery_document_for_settings,
)
from app.database import get_db
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


class ConfigResponse(BaseModel):
    runtime: RuntimeConfigSection
    auth: AuthConfigSection


class RuntimeConfigUpdate(BaseModel):
    max_concurrency: Optional[int] = None
    task_timeout: Optional[int] = None
    scheduler_interval: Optional[int] = None
    default_target_branch: Optional[str] = None


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


class ConfigUpdate(BaseModel):
    runtime: Optional[RuntimeConfigUpdate] = None
    auth: Optional[AuthConfigUpdate] = None


class OIDCConfigTestRequest(BaseModel):
    auth: AuthConfigUpdate


class OIDCConfigTestResponse(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    authorization_url_preview: str


def _serialize_effective_config() -> ConfigResponse:
    settings = get_effective_settings()
    return ConfigResponse(
        runtime=RuntimeConfigSection(
            max_concurrency=settings.max_concurrency,
            task_timeout=settings.task_timeout,
            scheduler_interval=settings.scheduler_interval,
            default_target_branch=settings.default_target_branch,
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
    )


def _is_valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _sanitize_string_list(value: str) -> str:
    return ",".join(item.strip() for item in value.split(",") if item.strip())


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

    if key == "oidc_enabled":
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="oidc_enabled must be a boolean",
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
        if key == "clear_oidc_client_secret":
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


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    """Get current configuration."""
    await load_runtime_config_from_db(db)
    return _serialize_effective_config()


@router.patch("/config")
async def update_config(
    config_update: ConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update persisted configuration overrides."""
    await load_runtime_config_from_db(db)

    runtime_updates = _normalize_updates(
        config_update.runtime.model_dump(exclude_unset=True) if config_update.runtime else {}
    )
    auth_updates = _normalize_updates(
        config_update.auth.model_dump(exclude_unset=True) if config_update.auth else {}
    )

    clear_secret = bool(auth_updates.pop("clear_oidc_client_secret", False))
    preview_updates = {**runtime_updates, **auth_updates}
    if clear_secret and "oidc_client_secret" not in auth_updates:
        preview_updates["oidc_client_secret"] = get_settings().oidc_client_secret

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

        if clear_secret and "oidc_client_secret" not in auth_updates:
            await reset_runtime_config_override(db, "oidc_client_secret")
            logger.info("Cleared stored OIDC client secret")

        await load_runtime_config_from_db(db)
    except ConfigEncryptionError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return _serialize_effective_config()


@router.post("/config/reset")
async def reset_config(db: AsyncSession = Depends(get_db)):
    """Reset all persisted configuration overrides back to env/default values."""
    await reset_all_runtime_config_overrides(db)
    await load_runtime_config_from_db(db)
    logger.info("Reset all persisted configuration overrides")
    return _serialize_effective_config()


@router.delete("/config/{key}")
async def reset_config_key(key: str, db: AsyncSession = Depends(get_db)):
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


@router.post("/config/oidc/test")
async def test_oidc_config(
    request: OIDCConfigTestRequest,
    db: AsyncSession = Depends(get_db),
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
    )
