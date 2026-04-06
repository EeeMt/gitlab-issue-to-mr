"""Authentication API endpoints."""

from __future__ import annotations

import logging
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
from app.core.bootstrap import get_bootstrap_state, initialize_system
from app.core.break_glass import get_break_glass_identity, verify_break_glass_password
from app.core.local_auth import hash_password, verify_password
from app.core.utcnow import utcnow
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
from app.models import AuthAuditLog, SystemBootstrap, User, UserSession
from app.page_permissions import get_page_permissions

logger = logging.getLogger(__name__)
router = APIRouter()

STATE_COOKIE_NAME = "codify_oidc_state"
NONCE_COOKIE_NAME = "codify_oidc_nonce"
NEXT_COOKIE_NAME = "codify_oidc_next"


class LocalLoginRequestBody(BaseModel):
    """Request body for local username/password login."""

    username: str
    password: str
    next: Optional[str] = None


class LocalRegisterRequestBody(BaseModel):
    """Request body for initial admin registration."""

    username: str
    password: str
    display_name: Optional[str] = None
    email: Optional[str] = None


class BootstrapStatusResponse(BaseModel):
    """Response for bootstrap status endpoint."""

    initialized: bool
    oidc_configured: bool
    total_users: int


class LocalLoginResponse(BaseModel):
    """Response for successful local login."""

    status: str
    next_path: str
    user: dict[str, Any]


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
    user.last_login_at = utcnow()
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

    result = await db.execute(
        select(User).where(
            (User.oidc_sub == oidc_sub) | (User.gitlab_user_id == gitlab_user_id)
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            oidc_sub=oidc_sub,
            gitlab_user_id=gitlab_user_id,
            username=username,
        )
        db.add(user)
    else:
        # Backfill identity fields for users created before oidc_sub was populated
        if not user.oidc_sub:
            user.oidc_sub = oidc_sub
        if not user.gitlab_user_id:
            user.gitlab_user_id = gitlab_user_id

    display_name = userinfo.get("name") or claims.get("name") or username
    email = userinfo.get("email") or claims.get("email")
    avatar_url = userinfo.get("picture") or claims.get("picture")
    user.username = username
    user.display_name = display_name
    user.email = email
    user.avatar_url = avatar_url
    user.auth_provider = "gitlab_oidc"
    user.last_login_at = utcnow()

    settings = get_effective_settings()
    groups = set()
    has_group_payload = False
    for source in (userinfo.get("groups"), claims.get("groups")):
        if source is not None:
            has_group_payload = True
        if isinstance(source, list):
            groups.update(str(item) for item in source)

    if settings.admin_gitlab_groups and not groups:
        logger.warning(
            "OIDC login for username=%s did not include usable GitLab groups while auth_admin_gitlab_groups is configured; has_userinfo_groups=%s has_claim_groups=%s configured_groups=%s",
            username,
            userinfo.get("groups") is not None,
            claims.get("groups") is not None,
            sorted(settings.admin_gitlab_groups),
        )
    elif settings.admin_gitlab_groups and has_group_payload:
        logger.info(
            "OIDC login for username=%s included GitLab groups for admin bootstrap evaluation",
            username,
        )

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



@router.get("/auth/bootstrap-status", response_model=BootstrapStatusResponse)
async def get_bootstrap_status(db: AsyncSession = Depends(get_db)):
    """Check if the system has been initialized."""
    state = await get_bootstrap_state(db)
    
    result = await db.execute(select(User))
    users = result.scalars().all()
    
    settings = get_effective_settings()
    
    return BootstrapStatusResponse(
        initialized=state.initialized,
        oidc_configured=settings.oidc_enabled,
        total_users=len(users),
    )


@router.post("/auth/local/register", response_model=LocalLoginResponse)
async def local_register(
    payload: LocalRegisterRequestBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register the initial admin user (only when system is not initialized)."""
    state = await get_bootstrap_state(db)
    if state.initialized:
        await _record_auth_audit(
            db,
            event_type="local_register",
            username=payload.username,
            user_id=None,
            success=False,
            detail="System already initialized",
            request=request,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System already initialized. Cannot register new users via this endpoint.",
        )
    
    username = payload.username.strip()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username is required",
        )
    
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none():
        await _record_auth_audit(
            db,
            event_type="local_register",
            username=username,
            user_id=None,
            success=False,
            detail="Username already exists",
            request=request,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )
    
    password_hash = hash_password(payload.password)
    
    user = User(
        username=username,
        display_name=payload.display_name or username,
        email=payload.email,
        local_password_hash=password_hash,
        auth_provider="local",
        platform_role="platform_admin",
        state="active",
    )
    db.add(user)
    await db.flush()

    # Mark system as initialized with this admin user
    await initialize_system(db, user)

    session_token = await create_user_session(
        db,
        user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    
    await _record_auth_audit(
        db,
        event_type="local_register",
        username=user.username,
        user_id=user.id,
        success=True,
        detail="Initial admin registration",
        request=request,
    )
    await db.commit()
    
    response = JSONResponse({
        "status": "success",
        "next_path": "/dashboard",
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "platform_role": user.platform_role,
        },
    })
    cookie_kwargs = _build_cookie_kwargs()
    response.set_cookie(
        get_effective_settings().session_cookie_name,
        session_token,
        max_age=get_effective_settings().session_ttl_seconds,
        **cookie_kwargs,
    )
    return response


@router.post("/auth/local/login", response_model=LocalLoginResponse)
async def local_login(
    payload: LocalLoginRequestBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with local username/password."""
    username = payload.username.strip()
    next_path = _sanitize_next_path(payload.next)
    
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    
    if not user or not user.local_password_hash:
        await _record_auth_audit(
            db,
            event_type="local_login",
            username=username,
            user_id=None,
            success=False,
            detail="User not found or no local password",
            request=request,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    
    if not verify_password(payload.password, user.local_password_hash):
        await _record_auth_audit(
            db,
            event_type="local_login",
            username=username,
            user_id=user.id,
            success=False,
            detail="Invalid password",
            request=request,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    
    if user.state != "active":
        await _record_auth_audit(
            db,
            event_type="local_login",
            username=username,
            user_id=user.id,
            success=False,
            detail="User account is disabled",
            request=request,
        )
        await db.commit()
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
    
    await _record_auth_audit(
        db,
        event_type="local_login",
        username=user.username,
        user_id=user.id,
        success=True,
        detail="Local login successful",
        request=request,
    )
    await db.commit()
    
    response = JSONResponse({
        "status": "success",
        "next_path": next_path,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "platform_role": user.platform_role,
        },
    })
    cookie_kwargs = _build_cookie_kwargs()
    response.set_cookie(
        get_effective_settings().session_cookie_name,
        session_token,
        max_age=get_effective_settings().session_ttl_seconds,
        **cookie_kwargs,
    )
    return response



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
            utcnow() + timedelta(seconds=int(tokens["expires_in"]))
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
    auth_context: AuthContext = Depends(require_authenticated_context),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's dashboard sessions."""
    result = await db.execute(
        select(UserSession)
        .where(UserSession.user_id == auth_context.user.id)
        .order_by(UserSession.created_at.desc())
    )
    now = utcnow()
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
    auth_context: AuthContext = Depends(require_authenticated_context),
    db: AsyncSession = Depends(get_db),
):
    """Revoke one dashboard session owned by the current user."""
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
    db: AsyncSession = Depends(get_db),
):
    """Return current auth state for frontend bootstrapping."""
    settings = get_effective_settings()
    
    # Get bootstrap state
    state = await get_bootstrap_state(db)
    
    if current_user is None:
        return {
            "oidc_enabled": settings.oidc_enabled,
            "break_glass_enabled": settings.break_glass_enabled,
            "break_glass_username": settings.auth_break_glass_username if settings.break_glass_enabled else None,
            "system_initialized": state.initialized,
            "authenticated": False,
            "page_permissions": get_page_permissions(None, settings),
            "user": None,
        }

    return {
        "oidc_enabled": settings.oidc_enabled,
        "break_glass_enabled": settings.break_glass_enabled,
        "break_glass_username": settings.auth_break_glass_username if settings.break_glass_enabled else None,
        "system_initialized": state.initialized,
        "authenticated": True,
        "page_permissions": get_page_permissions(current_user, settings),
        "user": {
            "id": current_user.id,
            "gitlab_user_id": current_user.gitlab_user_id,
            "username": current_user.username,
            "display_name": current_user.display_name,
            "email": current_user.email,
            "avatar_url": current_user.avatar_url,
            "platform_role": current_user.platform_role,
            "auth_provider": current_user.auth_provider,
        },
    }
