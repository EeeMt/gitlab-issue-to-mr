"""Helpers for resolving GitLab project-scoped access for dashboard users."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from fastapi import Depends, HTTPException, status

from app.config import get_effective_settings
from app.core.gitlab_client import get_accessible_projects_for_oauth_token
from app.core.oidc import exchange_refresh_token
from app.core.session import update_session_gitlab_tokens
from app.core.utcnow import utcnow
from app.database import AsyncSessionLocal
from app.dependencies.auth import AuthContext, require_authenticated_context

_ACCESS_CACHE_TTL_SECONDS = 300
# Cache stores (expires_at, projects_list); None means no data yet (cold).
_project_access_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
# Tracks in-flight background refresh tasks per session to avoid duplicate fetches.
_project_access_refresh_tasks: dict[str, asyncio.Task] = {}
logger = logging.getLogger(__name__)


def invalidate_project_access_cache() -> None:
    """Clear all per-user project access caches.

    Call this after the global GitLab project list cache is invalidated so that
    OIDC users also see freshly created/modified projects on their next request.
    """
    cleared = len(_project_access_cache)
    _project_access_cache.clear()
    for task in list(_project_access_refresh_tasks.values()):
        if not task.done():
            task.cancel()
    _project_access_refresh_tasks.clear()
    logger.info("Per-user project access cache cleared (%d entries removed)", cleared)


@dataclass
class ProjectAccessScope:
    """Resolved project access scope for the current request."""

    is_unrestricted: bool
    accessible_projects: list[dict[str, Any]]

    @property
    def accessible_project_ids(self) -> set[int]:
        return {int(project["id"]) for project in self.accessible_projects}

    def allows(self, project_id: int) -> bool:
        return self.is_unrestricted or project_id in self.accessible_project_ids


async def _fetch_and_cache_projects(
    session_id: str,
    access_token: str,
    session_expires_at: float,
) -> list[dict[str, Any]]:
    """Fetch accessible projects from GitLab and update the cache."""
    projects = await get_accessible_projects_for_oauth_token(access_token)
    now = time.time()
    cache_expires_at = min(now + _ACCESS_CACHE_TTL_SECONDS, session_expires_at)
    _project_access_cache[session_id] = (cache_expires_at, projects)
    _project_access_refresh_tasks.pop(session_id, None)
    return projects


async def require_project_access_scope(
    auth_context: Optional[AuthContext] = Depends(require_authenticated_context),
) -> ProjectAccessScope:
    """Resolve the set of GitLab projects the current user may access.

    Uses stale-while-revalidate: returns cached data immediately on cache
    expiry and refreshes in the background, so polling endpoints never block
    on a GitLab API round-trip.

    Does NOT depend on get_db — any required DB writes (token refresh/revocation)
    are performed in short-lived sessions created internally.  This makes it safe
    to use on long-lived streaming endpoints without holding a DB connection for
    the entire response duration.
    """
    t_start = time.time()
    settings = get_effective_settings()
    if not settings.oidc_enabled or auth_context is None:
        return ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    if auth_context.user.platform_role == "platform_admin":
        return ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    if not auth_context.gitlab_access_token:
        await _refresh_auth_context_tokens(auth_context)
        if not auth_context.gitlab_access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session is missing GitLab API access. Please sign in again.",
            )

    session_id = auth_context.session.id
    cache_entry = _project_access_cache.get(session_id)
    now = time.time()
    session_expires_at = (
        auth_context.session.expires_at.timestamp()
        if auth_context.session.expires_at is not None
        else now + _ACCESS_CACHE_TTL_SECONDS
    )

    if cache_entry and cache_entry[0] > now:
        # Fresh cache — return immediately.
        projects = cache_entry[1]
    elif cache_entry:
        # Stale cache — return immediately and refresh in background.
        projects = cache_entry[1]
        existing_task = _project_access_refresh_tasks.get(session_id)
        if existing_task is None or existing_task.done():
            _project_access_refresh_tasks[session_id] = asyncio.create_task(
                _fetch_and_cache_projects(
                    session_id,
                    auth_context.gitlab_access_token,
                    session_expires_at,
                )
            )
    else:
        # Cold cache — must block on the first fetch.
        try:
            projects = await _fetch_and_cache_projects(
                session_id,
                auth_context.gitlab_access_token,
                session_expires_at,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                refreshed = await _refresh_auth_context_tokens(auth_context)
                if refreshed:
                    try:
                        projects = await _fetch_and_cache_projects(
                            session_id,
                            auth_context.gitlab_access_token,
                            session_expires_at,
                        )
                    except httpx.HTTPStatusError as retry_exc:
                        if retry_exc.response.status_code in {401, 403}:
                            raise HTTPException(
                                status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="GitLab login expired and refresh failed. Please sign in again.",
                            ) from retry_exc
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Failed to resolve GitLab project access for the current user.",
                        ) from retry_exc
                    except httpx.HTTPError as retry_exc:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Failed to reach GitLab while refreshing project access.",
                        ) from retry_exc
                else:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="GitLab login expired and refresh is unavailable. Please sign in again.",
                    ) from exc
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to resolve GitLab project access for the current user.",
                ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to reach GitLab while resolving project access.",
            ) from exc

    elapsed = time.time() - t_start
    if elapsed > 1.0:
        logger.warning(
            f"[SLOW require_project_access_scope] {elapsed:.3f}s "
            f"user={auth_context.user.username if auth_context else None} "
            f"cache_hit={bool(cache_entry and cache_entry[0] > time.time())}"
        )

    return ProjectAccessScope(is_unrestricted=False, accessible_projects=projects)


def require_project_access(project_id: int, scope: ProjectAccessScope) -> None:
    """Enforce access to a specific GitLab project."""
    if scope.allows(project_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Project {project_id} is not accessible for the current user",
    )


async def _refresh_auth_context_tokens(auth_context: AuthContext) -> bool:
    """Refresh an expired GitLab access token for the current session when possible.

    Creates a short-lived DB session internally so callers (including streaming
    endpoints) are not required to hold an open session for this rare path.
    """
    if not auth_context.gitlab_refresh_token:
        logger.info(
            "GitLab token refresh skipped because no refresh token is stored for session %s (user_id=%s)",
            auth_context.session.id,
            auth_context.user.id,
        )
        return False

    try:
        tokens = await exchange_refresh_token(auth_context.gitlab_refresh_token)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {400, 401, 403}:
            logger.warning(
                "GitLab token refresh rejected for session %s (user_id=%s, status=%s); revoking session",
                auth_context.session.id,
                auth_context.user.id,
                exc.response.status_code,
            )
            async with AsyncSessionLocal() as db:
                auth_context.session.revoked_at = utcnow()
                db.add(auth_context.session)
                await db.commit()
            _project_access_cache.pop(auth_context.session.id, None)
            return False
        logger.exception(
            "GitLab token refresh failed unexpectedly for session %s (user_id=%s, status=%s)",
            auth_context.session.id,
            auth_context.user.id,
            exc.response.status_code,
        )
        raise
    except httpx.HTTPError:
        logger.exception(
            "GitLab token refresh request errored for session %s (user_id=%s)",
            auth_context.session.id,
            auth_context.user.id,
        )
        raise

    access_token = tokens.get("access_token")
    if not access_token:
        logger.warning(
            "GitLab token refresh returned no access token for session %s (user_id=%s); revoking session",
            auth_context.session.id,
            auth_context.user.id,
        )
        async with AsyncSessionLocal() as db:
            auth_context.session.revoked_at = utcnow()
            db.add(auth_context.session)
            await db.commit()
        _project_access_cache.pop(auth_context.session.id, None)
        return False

    refresh_token = tokens.get("refresh_token") or auth_context.gitlab_refresh_token
    max_expires_at = (
        utcnow() + timedelta(seconds=int(tokens["expires_in"]))
        if tokens.get("expires_in")
        else None
    )
    async with AsyncSessionLocal() as db:
        await update_session_gitlab_tokens(
            db,
            auth_context.session,
            gitlab_access_token=access_token,
            gitlab_refresh_token=refresh_token,
            max_expires_at=max_expires_at,
        )
        await db.commit()
    auth_context.gitlab_access_token = access_token
    auth_context.gitlab_refresh_token = refresh_token
    _project_access_cache.pop(auth_context.session.id, None)
    return True
