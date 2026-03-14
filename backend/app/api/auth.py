"""Authentication API endpoints."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Optional

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.core.oidc import (
    OIDCConfigurationError,
    build_authorization_url,
    exchange_code_for_tokens,
    fetch_userinfo,
    validate_id_token,
)
from app.core.session import create_user_session, revoke_session_token
from app.database import get_db
from app.dependencies.auth import get_optional_current_user
from app.models import User

router = APIRouter()

STATE_COOKIE_NAME = "gimr_oidc_state"
NONCE_COOKIE_NAME = "gimr_oidc_nonce"
NEXT_COOKIE_NAME = "gimr_oidc_next"


def _build_cookie_kwargs() -> dict[str, Any]:
    settings = get_effective_settings()
    return {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "path": "/",
    }


def _sanitize_next_path(next_path: Optional[str]) -> str:
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return "/dashboard"
    return next_path


async def _upsert_user(db: AsyncSession, claims: dict[str, Any], userinfo: dict[str, Any]) -> User:
    oidc_sub = str(claims.get("sub") or userinfo.get("sub") or "").strip()
    username = (
        userinfo.get("preferred_username")
        or claims.get("preferred_username")
        or userinfo.get("nickname")
        or ""
    ).strip()
    if not oidc_sub or not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OIDC response missing required identity fields",
        )

    try:
        gitlab_user_id = int(oidc_sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OIDC sub is not a valid GitLab user ID",
        ) from exc

    result = await db.execute(select(User).where(User.oidc_sub == oidc_sub))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            oidc_sub=oidc_sub,
            gitlab_user_id=gitlab_user_id,
            username=username,
        )
        db.add(user)

    display_name = userinfo.get("name") or claims.get("name") or username
    email = userinfo.get("email") or claims.get("email")
    avatar_url = userinfo.get("picture") or claims.get("picture")
    user.username = username
    user.display_name = display_name
    user.email = email
    user.avatar_url = avatar_url
    user.last_login_at = datetime.utcnow()

    settings = get_effective_settings()
    groups = set()
    for source in (userinfo.get("groups"), claims.get("groups")):
        if isinstance(source, list):
            groups.update(str(item) for item in source)

    if user.platform_role == "disabled" or user.state == "disabled":
        user.platform_role = "disabled"
        user.state = "disabled"
    elif (
        user.platform_role == "platform_admin"
        or username in settings.admin_usernames
        or groups.intersection(settings.admin_gitlab_groups)
    ):
        user.platform_role = "platform_admin"
    else:
        user.platform_role = "platform_user"
        user.state = "active"

    await db.flush()
    return user


@router.get("/auth/login")
async def login(next: Optional[str] = Query(default=None)):
    """Redirect the browser to the GitLab OIDC authorize endpoint."""
    settings = get_effective_settings()
    if not settings.oidc_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC login is disabled",
        )

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    safe_next = _sanitize_next_path(next)

    try:
        authorize_url = await build_authorization_url(state, nonce)
    except OIDCConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    response = RedirectResponse(authorize_url, status_code=status.HTTP_302_FOUND)
    cookie_kwargs = _build_cookie_kwargs()
    response.set_cookie(STATE_COOKIE_NAME, state, max_age=600, **cookie_kwargs)
    response.set_cookie(NONCE_COOKIE_NAME, nonce, max_age=600, **cookie_kwargs)
    response.set_cookie(NEXT_COOKIE_NAME, safe_next, max_age=600, **cookie_kwargs)
    return response


@router.get("/auth/callback")
async def callback(
    request: Request,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Handle the GitLab OIDC callback."""
    settings = get_effective_settings()
    if not settings.oidc_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC login is disabled",
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OIDC callback parameters",
        )

    expected_state = request.cookies.get(STATE_COOKIE_NAME)
    nonce = request.cookies.get(NONCE_COOKIE_NAME)
    next_path = _sanitize_next_path(request.cookies.get(NEXT_COOKIE_NAME))
    if not expected_state or state != expected_state or not nonce:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OIDC state",
        )

    try:
        tokens = await exchange_code_for_tokens(code)
        claims = await validate_id_token(tokens["id_token"], nonce)
        userinfo = await fetch_userinfo(tokens["access_token"])
    except (OIDCConfigurationError, httpx.HTTPError, jwt.PyJWTError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"OIDC authentication failed: {exc}",
        ) from exc
    user = await _upsert_user(db, claims, userinfo)
    if user.state != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    session_token = await create_user_session(
        db,
        user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    response = RedirectResponse(next_path, status_code=status.HTTP_302_FOUND)
    cookie_kwargs = _build_cookie_kwargs()
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        **cookie_kwargs,
    )
    response.delete_cookie(STATE_COOKIE_NAME, path="/")
    response.delete_cookie(NONCE_COOKIE_NAME, path="/")
    response.delete_cookie(NEXT_COOKIE_NAME, path="/")
    return response


@router.post("/auth/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Log the current user out."""
    settings = get_effective_settings()
    token = request.cookies.get(settings.session_cookie_name)
    await revoke_session_token(db, token)
    response = JSONResponse({"status": "success"})
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@router.get("/auth/me")
async def me(
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """Return current auth state for frontend bootstrapping."""
    settings = get_effective_settings()
    if not settings.oidc_enabled:
        return {
            "oidc_enabled": False,
            "authenticated": False,
            "user": None,
        }

    if current_user is None:
        return {
            "oidc_enabled": True,
            "authenticated": False,
            "user": None,
        }

    return {
        "oidc_enabled": True,
        "authenticated": True,
        "user": {
            "id": current_user.id,
            "gitlab_user_id": current_user.gitlab_user_id,
            "username": current_user.username,
            "display_name": current_user.display_name,
            "email": current_user.email,
            "avatar_url": current_user.avatar_url,
            "platform_role": current_user.platform_role,
        },
    }
