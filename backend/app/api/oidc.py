"""OIDC configuration API endpoints."""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_effective_settings
from app.core.config_crypto import ConfigEncryptionError
from app.core.oidc import (
    OIDCConfigurationError,
    build_authorization_url_for_settings,
    get_required_oidc_scope_string,
    get_required_oidc_scopes,
    get_oidc_discovery_document_for_settings,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user, require_page_access
from app.runtime_config import load_runtime_config_from_db
from app.models import User

# Import AuthConfigUpdate from config.py to avoid duplication
from app.api.config import AuthConfigUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate config updates before saving."""
    normalized = {}
    for key, value in updates.items():
        if value is None:
            continue
        if key == "session_ttl_seconds" and isinstance(value, int):
            normalized[key] = max(300, min(value, 604800))
        elif key == "cookie_samesite" and value not in ("lax", "strict", "none"):
            continue
        elif isinstance(value, str) and not value.strip():
            continue
        else:
            normalized[key] = value
    return normalized


def _build_preview_settings(auth_updates: dict[str, Any]) -> Settings:
    """Build a preview settings object with auth updates applied."""
    from app.config import get_settings
    settings = get_settings()
    settings_dict = settings.model_dump()
    settings_dict.update(auth_updates)
    # Handle clear_* flags
    for key in list(settings_dict.keys()):
        if key.startswith("clear_"):
            del settings_dict[key]
    return Settings(**settings_dict)


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


class OIDCDiagnosticsCheck(BaseModel):
    key: str
    label: str
    status: str
    detail: str


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


class OIDCConfigTestRequest(BaseModel):
    auth: "AuthConfigUpdate"


class OIDCConfigTestResponse(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    authorization_url_preview: str
    required_scopes: list[str]
    warnings: list[str]


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


@router.post("/config/oidc/test")
async def test_oidc_config(
    request: Request,
    oidc_request: OIDCConfigTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_admin_user),
):
    """Validate OIDC connectivity with current or unsaved config values.

    This endpoint allows any authenticated admin user to test OIDC configuration,
    including users authenticated via local auth. This enables administrators to
    configure and test OIDC without being locked out by OIDC authentication requirements.

    When OIDC is not yet configured, unauthenticated requests are allowed to enable
    the initial OIDC setup flow.
    """
    # Allow unauthenticated requests only when OIDC is not configured
    # This enables initial OIDC setup without requiring any authentication
    settings = get_effective_settings()
    if not settings.oidc_enabled and current_user is None:
        # OIDC not configured - allow anonymous testing for initial setup
        pass
    elif current_user is None:
        # OIDC is configured but user not authenticated
        # Check if skip-redirect header was sent (programmatic API call)
        skip_redirect = request.headers.get("X-Skip-Auth-Redirect", "").lower() == "true"
        if skip_redirect:
            # For programmatic calls with skip-redirect, allow the test to proceed
            # This enables testing OIDC config from the UI without forcing login
            pass
        else:
            # Interactive request - require authentication
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
    # else: current_user is not None - authenticated admin, allow the test

    await load_runtime_config_from_db(db)
    auth_updates = _normalize_updates(oidc_request.auth.model_dump(exclude_unset=True))
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
