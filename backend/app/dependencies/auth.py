"""Authentication dependencies for dashboard APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.core.session import (
    get_gitlab_access_token_from_session,
    get_user_and_session_from_session_token,
)
from app.database import get_db
from app.models import User, UserSession


@dataclass
class AuthContext:
    """Resolved authenticated context for the current request."""

    user: User
    session: UserSession
    gitlab_access_token: str | None


async def get_optional_auth_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[AuthContext]:
    """Resolve the current auth context from the session cookie if auth is enabled."""
    settings = get_effective_settings()
    if not settings.oidc_enabled:
        return None

    token = request.cookies.get(settings.session_cookie_name)
    user, session = await get_user_and_session_from_session_token(db, token)
    if user is None or session is None:
        return None
    return AuthContext(
        user=user,
        session=session,
        gitlab_access_token=get_gitlab_access_token_from_session(session),
    )


async def get_optional_current_user(
    auth_context: Optional[AuthContext] = Depends(get_optional_auth_context),
) -> Optional[User]:
    """Resolve the current user from the auth context if auth is enabled."""
    return auth_context.user if auth_context is not None else None


async def require_authenticated_context(
    auth_context: Optional[AuthContext] = Depends(get_optional_auth_context),
) -> Optional[AuthContext]:
    """Require an authenticated request context when OIDC is enabled."""
    settings = get_effective_settings()
    if not settings.oidc_enabled:
        return None
    if auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return auth_context


async def require_authenticated_user(
    auth_context: Optional[AuthContext] = Depends(require_authenticated_context),
) -> Optional[User]:
    """Require an authenticated user when OIDC is enabled."""
    settings = get_effective_settings()
    if not settings.oidc_enabled:
        return None
    return auth_context.user if auth_context is not None else None


async def require_admin_user(
    auth_context: Optional[AuthContext] = Depends(require_authenticated_context),
) -> Optional[User]:
    """Require an admin user when auth is enabled."""
    settings = get_effective_settings()
    if not settings.oidc_enabled:
        return None
    current_user = auth_context.user if auth_context is not None else None
    if current_user is None or current_user.platform_role != "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
