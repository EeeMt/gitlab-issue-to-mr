"""Authentication dependencies for dashboard APIs."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.core.session import (
    get_gitlab_refresh_token_from_session,
    get_gitlab_access_token_from_session,
    resolve_session_authentication,
)
from app.database import get_db
from app.models import User, UserSession
from app.page_permissions import can_access_page
from app.runtime_config import load_runtime_config_from_db

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """Resolved authenticated context for the current request."""

    user: User
    session: UserSession
    gitlab_access_token: str | None
    gitlab_refresh_token: str | None


async def get_optional_auth_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[AuthContext]:
    """Resolve the current auth context from the session cookie if auth is enabled."""
    t0 = time.time()
    await load_runtime_config_from_db(db)
    t1 = time.time()
    settings = get_effective_settings()

    token = request.cookies.get(settings.session_cookie_name)
    result = await resolve_session_authentication(db, token)
    t2 = time.time()

    if t1 - t0 > 1.0:
        logger.warning(f"[SLOW auth] load_runtime_config={t1-t0:.3f}s path={request.url.path}")
    if t2 - t1 > 1.0:
        logger.warning(f"[SLOW auth] resolve_session={t2-t1:.3f}s path={request.url.path}")

    request.state.auth_failure_detail = result.failure_detail
    if result.user is None or result.session is None:
        return None
    return AuthContext(
        user=result.user,
        session=result.session,
        gitlab_access_token=get_gitlab_access_token_from_session(result.session),
        gitlab_refresh_token=get_gitlab_refresh_token_from_session(result.session),
    )


async def get_optional_current_user(
    auth_context: Optional[AuthContext] = Depends(get_optional_auth_context),
) -> Optional[User]:
    """Resolve the current user from the auth context if auth is enabled."""
    return auth_context.user if auth_context is not None else None


async def require_authenticated_context(
    request: Request,
    auth_context: Optional[AuthContext] = Depends(get_optional_auth_context),
) -> Optional[AuthContext]:
    """Require an authenticated request context.

    If the X-Skip-Auth-Redirect header is present, return None instead of raising
    an exception to allow the client to handle authentication failures gracefully.
    """
    # Allow clients to skip auth redirect for programmatic API calls
    skip_redirect = request.headers.get("X-Skip-Auth-Redirect", "").lower() == "true"

    if auth_context is None:
        if skip_redirect:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=getattr(request.state, "auth_failure_detail", None) or "Authentication required",
        )
    return auth_context


async def require_authenticated_user(
    auth_context: Optional[AuthContext] = Depends(require_authenticated_context),
) -> Optional[User]:
    """Require an authenticated user."""
    return auth_context.user if auth_context is not None else None


async def require_admin_user(
    request: Request,
    auth_context: Optional[AuthContext] = Depends(require_authenticated_context),
) -> Optional[User]:
    """Require an admin user."""
    # require_authenticated_context already validates auth
    current_user = auth_context.user
    if current_user.platform_role != "platform_admin":
        skip_redirect = request.headers.get("X-Skip-Auth-Redirect", "").lower() == "true"
        if skip_redirect:
            return None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def require_page_access(page_key: str):
    """Require access to a configured shared page."""

    async def _require_page_access(
        auth_context: Optional[AuthContext] = Depends(require_authenticated_context),
    ) -> Optional[User]:
        settings = get_effective_settings()
        current_user = auth_context.user if auth_context is not None else None
        if can_access_page(page_key, current_user, settings):
            return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this page is restricted",
        )

    return _require_page_access
