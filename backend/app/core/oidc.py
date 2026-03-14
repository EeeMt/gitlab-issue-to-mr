"""GitLab OIDC client helpers."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from app.config import Settings, get_effective_settings

_discovery_cache: dict[str, Any] = {"issuer": "", "expires_at": 0.0, "document": None}
REQUIRED_OIDC_SCOPES = ("openid", "profile", "email", "read_api")


def get_required_oidc_scopes() -> tuple[str, ...]:
    """Return the OAuth scopes required by the dashboard."""
    return REQUIRED_OIDC_SCOPES


def get_required_oidc_scope_string() -> str:
    """Return the OAuth scope string used in authorization URLs."""
    return " ".join(REQUIRED_OIDC_SCOPES)


class OIDCConfigurationError(RuntimeError):
    """OIDC is not configured correctly."""


def ensure_oidc_configured(
    settings: Settings,
    *,
    require_enabled: bool = True,
    require_client_secret: bool = True,
) -> None:
    """Validate the OIDC-related settings required for an operation."""
    if require_enabled and not settings.oidc_enabled:
        raise OIDCConfigurationError("OIDC is disabled")
    if not settings.oidc_issuer_url or not settings.oidc_client_id or not settings.oidc_redirect_uri:
        raise OIDCConfigurationError("OIDC settings are incomplete")
    if require_client_secret and not settings.oidc_client_secret:
        raise OIDCConfigurationError("OIDC client secret is not configured")


async def get_oidc_discovery_document_for_settings(settings: Settings) -> dict[str, Any]:
    """Fetch and cache the OIDC discovery document for the configured issuer."""
    ensure_oidc_configured(settings, require_client_secret=False)

    now = time.time()
    issuer = settings.oidc_issuer_url.rstrip("/")
    if (
        _discovery_cache["document"]
        and _discovery_cache["issuer"] == issuer
        and _discovery_cache["expires_at"] > now
    ):
        return _discovery_cache["document"]

    discovery_url = f"{issuer}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(discovery_url)
        response.raise_for_status()
        document = response.json()

    _discovery_cache["issuer"] = issuer
    _discovery_cache["document"] = document
    _discovery_cache["expires_at"] = now + 300
    return document


async def get_oidc_discovery_document() -> dict[str, Any]:
    """Fetch the discovery document using the current effective settings."""
    return await get_oidc_discovery_document_for_settings(get_effective_settings())


async def build_authorization_url_for_settings(settings: Settings, state: str, nonce: str) -> str:
    """Build the authorize URL for the provided settings."""
    discovery = await get_oidc_discovery_document_for_settings(settings)
    params = {
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "response_type": "code",
        "scope": get_required_oidc_scope_string(),
        "state": state,
        "nonce": nonce,
    }
    return f"{discovery['authorization_endpoint']}?{urlencode(params)}"


async def build_authorization_url(state: str, nonce: str) -> str:
    """Build the authorize URL from the effective runtime settings."""
    return await build_authorization_url_for_settings(get_effective_settings(), state, nonce)


async def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    """Exchange an authorization code for tokens."""
    settings = get_effective_settings()
    ensure_oidc_configured(settings)
    discovery = await get_oidc_discovery_document_for_settings(settings)
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_uri,
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            discovery["token_endpoint"],
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()


async def exchange_refresh_token(refresh_token: str) -> dict[str, Any]:
    """Exchange a refresh token for a new access token."""
    settings = get_effective_settings()
    ensure_oidc_configured(settings)
    discovery = await get_oidc_discovery_document_for_settings(settings)
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            discovery["token_endpoint"],
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()


async def fetch_userinfo(access_token: str) -> dict[str, Any]:
    """Fetch userinfo for the authenticated subject."""
    discovery = await get_oidc_discovery_document_for_settings(get_effective_settings())
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            discovery["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


async def validate_id_token(id_token: str, nonce: str) -> dict[str, Any]:
    """Validate and decode the ID token."""
    settings = get_effective_settings()
    discovery = await get_oidc_discovery_document_for_settings(settings)

    def decode_token() -> dict[str, Any]:
        jwk_client = PyJWKClient(discovery["jwks_uri"])
        signing_key = jwk_client.get_signing_key_from_jwt(id_token)
        return jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512"],
            audience=settings.oidc_client_id,
            issuer=discovery["issuer"],
        )

    claims = await asyncio.to_thread(decode_token)
    if claims.get("nonce") != nonce:
        raise jwt.InvalidTokenError("OIDC nonce mismatch")
    return claims
