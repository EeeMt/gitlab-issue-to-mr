"""Authentication dependencies for dashboard APIs."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.session import get_user_from_session_token
from app.database import get_db
from app.models import User


async def get_optional_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Resolve the current user from the session cookie if auth is enabled."""
    settings = get_settings()
    if not settings.oidc_enabled:
        return None

    token = request.cookies.get(settings.session_cookie_name)
    return await get_user_from_session_token(db, token)


async def require_authenticated_user(
    current_user: Optional[User] = Depends(get_optional_current_user),
) -> Optional[User]:
    """Require an authenticated user when OIDC is enabled."""
    settings = get_settings()
    if not settings.oidc_enabled:
        return None
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return current_user


async def require_admin_user(
    current_user: Optional[User] = Depends(require_authenticated_user),
) -> Optional[User]:
    """Require an admin user when auth is enabled."""
    settings = get_settings()
    if not settings.oidc_enabled:
        return None
    if current_user is None or current_user.platform_role != "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
