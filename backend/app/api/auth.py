"""Authentication API endpoints."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.core.break_glass import get_break_glass_identity, verify_break_glass_password
from app.core.oidc import (
    OIDCConfigurationError,
    build_authorization_url,
    exchange_code_for_tokens,
    fetch_userinfo,
    validate_id_token,
)
from app.core.session import (
    create_user_session,
    revoke_session_by_id,
    revoke_session_token,
)
from app.core.user_roles import ROLE_SOURCE_BREAK_GLASS, apply_platform_access_policy
from app.database import get_db
from app.dependencies.auth import (
    AuthContext,
    get_optional_current_user,
    require_authenticated_context,
)
from app.models import AuthAuditLog, User, UserSession

router = APIRouter()

STATE_COOKIE_NAME = "gimr_oidc_state"
NONCE_COOKIE_NAME = "gimr_oidc_nonce"
NEXT_COOKIE_NAME = "gimr_oidc_next"


class BreakGlassLoginRequestBody(BaseModel):
    """Request body for emergency admin login."""

    username: str
    password: str
    next: Optional[str] = None


class SessionInfoResponse(BaseModel):
    id: str
    created_at: datetime
    last_seen_at: Optional[datetime]
    expires_at: datetime
    revoked_at: Optional[datetime]
    ip_address: Optional[str]
    user_agent: Optional[str]
    status: str
    current: bool
    has_gitlab_access_token: bool
    has_gitlab_refresh_token: bool


class RevokeSessionResponse(BaseModel):
    status: str
    session_id: str
    current_session_revoked: bool


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


async def _record_auth_audit(
    db: AsyncSession,
    *,
    event_type: str,
    username: Optional[str],
    user_id: Optional[int],
    success: bool,
    detail: Optional[str],
    request: Request,
) -> None:
    db.add(
        AuthAuditLog(
            event_type=event_type,
            username=username,
            user_id=user_id,
            success=success,
            detail=detail,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    await db.flush()


async def _get_or_create_break_glass_user(db: AsyncSession, username: str) -> User:
    oidc_sub, gitlab_user_id = get_break_glass_identity(username)
    result = await db.execute(select(User).where(User.oidc_sub == oidc_sub))
    user = result.scalar_one_or_none()

    if user is None:
        conflicting_username = await db.execute(select(User).where(User.username == username))
        existing_by_username = conflicting_username.scalar_one_or_none()
        if existing_by_username is not None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Break-glass username conflicts with an existing dashboard user",
            )

        user = User(
            oidc_sub=oidc_sub,
            gitlab_user_id=gitlab_user_id,
            username=username,
        )
        db.add(user)

    user.display_name = "Emergency Admin"
    user.email = None
    user.avatar_url = None
    user.platform_role = "platform_admin"
    user.platform_role_source = ROLE_SOURCE_BREAK_GLASS
    user.state = "active"
    user.last_login_at = datetime.utcnow()
    await db.flush()
    return user


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

    apply_platform_access_policy(
        user,
        username=username,
        groups=groups,
        admin_usernames=settings.admin_usernames,
        admin_gitlab_groups=settings.admin_gitlab_groups,
    )
    if user.state != "disabled":
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


@router.post("/auth/break-glass/login")
async def break_glass_login(
    payload: BreakGlassLoginRequestBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate through the emergency break-glass admin path."""
    settings = get_effective_settings()
    if not settings.break_glass_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Break-glass login is not enabled",
        )

    username = payload.username.strip()
    next_path = _sanitize_next_path(payload.next)
    if username != settings.auth_break_glass_username.strip() or not verify_break_glass_password(
        payload.password,
        settings.auth_break_glass_password_hash,
    ):
        await _record_auth_audit(
            db,
            event_type="break_glass_login",
            username=username or None,
            user_id=None,
            success=False,
            detail="Invalid emergency credentials",
            request=request,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid break-glass credentials",
        )

    user = await _get_or_create_break_glass_user(db, username)
    session_token = await create_user_session(
        db,
        user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await _record_auth_audit(
        db,
        event_type="break_glass_login",
        username=user.username,
        user_id=user.id,
        success=True,
        detail="Emergency admin login",
        request=request,
    )
    await db.commit()

    response = JSONResponse({"status": "success", "next_path": next_path})
    cookie_kwargs = _build_cookie_kwargs()
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        **cookie_kwargs,
    )
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
        gitlab_access_token=tokens.get("access_token"),
        gitlab_refresh_token=tokens.get("refresh_token"),
        max_expires_at=(
            datetime.utcnow() + timedelta(seconds=int(tokens["expires_in"]))
            if tokens.get("expires_in")
            else None
        ),
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


@router.get("/auth/sessions", response_model=list[SessionInfoResponse])
async def list_sessions(
    auth_context: Optional[AuthContext] = Depends(require_authenticated_context),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's dashboard sessions."""
    settings = get_effective_settings()
    if not settings.oidc_enabled or auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session management is only available when OIDC is enabled.",
        )

    result = await db.execute(
        select(UserSession)
        .where(UserSession.user_id == auth_context.user.id)
        .order_by(UserSession.created_at.desc())
    )
    now = datetime.utcnow()
    sessions = result.scalars().all()
    return [
        SessionInfoResponse(
            id=session.id,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            expires_at=session.expires_at,
            revoked_at=session.revoked_at,
            ip_address=session.ip_address,
            user_agent=session.user_agent,
            status=(
                "revoked"
                if session.revoked_at
                else "expired"
                if session.expires_at <= now
                else "active"
            ),
            current=session.id == auth_context.session.id,
            has_gitlab_access_token=bool(session.gitlab_access_token_encrypted),
            has_gitlab_refresh_token=bool(session.gitlab_refresh_token_encrypted),
        )
        for session in sessions
    ]


@router.post("/auth/sessions/{session_id}/revoke", response_model=RevokeSessionResponse)
async def revoke_session(
    session_id: str,
    auth_context: Optional[AuthContext] = Depends(require_authenticated_context),
    db: AsyncSession = Depends(get_db),
):
    """Revoke one dashboard session owned by the current user."""
    settings = get_effective_settings()
    if not settings.oidc_enabled or auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session management is only available when OIDC is enabled.",
        )

    result = await db.execute(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == auth_context.user.id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    revoked = await revoke_session_by_id(db, session_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session has already been revoked",
        )
    await db.commit()
    return RevokeSessionResponse(
        status="success",
        session_id=session_id,
        current_session_revoked=session_id == auth_context.session.id,
    )


@router.get("/auth/me")
async def me(
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """Return current auth state for frontend bootstrapping."""
    settings = get_effective_settings()
    if not settings.oidc_enabled:
        return {
            "oidc_enabled": False,
            "break_glass_enabled": settings.break_glass_enabled,
            "break_glass_username": settings.auth_break_glass_username if settings.break_glass_enabled else None,
            "authenticated": False,
            "user": None,
        }

    if current_user is None:
        return {
            "oidc_enabled": True,
            "break_glass_enabled": settings.break_glass_enabled,
            "break_glass_username": settings.auth_break_glass_username if settings.break_glass_enabled else None,
            "authenticated": False,
            "user": None,
        }

    return {
        "oidc_enabled": True,
        "break_glass_enabled": settings.break_glass_enabled,
        "break_glass_username": settings.auth_break_glass_username if settings.break_glass_enabled else None,
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
