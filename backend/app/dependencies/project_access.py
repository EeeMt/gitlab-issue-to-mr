"""Helpers for resolving GitLab project-scoped access for dashboard users."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.core.gitlab_client import get_accessible_projects_for_oauth_token
from app.core.oidc import exchange_refresh_token
from app.core.session import update_session_gitlab_tokens
from app.database import get_db
from app.dependencies.auth import AuthContext, require_authenticated_context

_ACCESS_CACHE_TTL_SECONDS = 60
_project_access_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


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


async def require_project_access_scope(
    auth_context: Optional[AuthContext] = Depends(require_authenticated_context),
    db: AsyncSession = Depends(get_db),
) -> ProjectAccessScope:
    """Resolve the set of GitLab projects the current user may access."""
    settings = get_effective_settings()
    if not settings.oidc_enabled or auth_context is None:
        return ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    if auth_context.user.platform_role == "platform_admin":
        return ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    if not auth_context.gitlab_access_token:
        await _refresh_auth_context_tokens(auth_context, db)
        if not auth_context.gitlab_access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session is missing GitLab API access. Please sign in again.",
            )

    cache_entry = _project_access_cache.get(auth_context.session.id)
    now = time.time()
    if cache_entry and cache_entry[0] > now:
        projects = cache_entry[1]
    else:
        try:
            projects = await get_accessible_projects_for_oauth_token(auth_context.gitlab_access_token)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                refreshed = await _refresh_auth_context_tokens(auth_context, db)
                if refreshed:
                    try:
                        projects = await get_accessible_projects_for_oauth_token(
                            auth_context.gitlab_access_token
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
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to resolve GitLab project access for the current user.",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to reach GitLab while resolving project access.",
            ) from exc
        session_expires_at = (
            auth_context.session.expires_at.timestamp()
            if auth_context.session.expires_at is not None
            else now + _ACCESS_CACHE_TTL_SECONDS
        )
        cache_expires_at = min(now + _ACCESS_CACHE_TTL_SECONDS, session_expires_at)
        _project_access_cache[auth_context.session.id] = (cache_expires_at, projects)

    return ProjectAccessScope(is_unrestricted=False, accessible_projects=projects)


def require_project_access(project_id: int, scope: ProjectAccessScope) -> None:
    """Enforce access to a specific GitLab project."""
    if scope.allows(project_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Project {project_id} is not accessible for the current user",
    )


async def _refresh_auth_context_tokens(auth_context: AuthContext, db: AsyncSession) -> bool:
    """Refresh an expired GitLab access token for the current session when possible."""
    if not auth_context.gitlab_refresh_token:
        return False

    try:
        tokens = await exchange_refresh_token(auth_context.gitlab_refresh_token)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {400, 401, 403}:
            auth_context.session.revoked_at = datetime.utcnow()
            await db.flush()
            _project_access_cache.pop(auth_context.session.id, None)
            return False
        raise

    access_token = tokens.get("access_token")
    if not access_token:
        auth_context.session.revoked_at = datetime.utcnow()
        await db.flush()
        _project_access_cache.pop(auth_context.session.id, None)
        return False

    refresh_token = tokens.get("refresh_token") or auth_context.gitlab_refresh_token
    max_expires_at = (
        datetime.utcnow() + timedelta(seconds=int(tokens["expires_in"]))
        if tokens.get("expires_in")
        else None
    )
    await update_session_gitlab_tokens(
        db,
        auth_context.session,
        gitlab_access_token=access_token,
        gitlab_refresh_token=refresh_token,
        max_expires_at=max_expires_at,
    )
    auth_context.gitlab_access_token = access_token
    auth_context.gitlab_refresh_token = refresh_token
    _project_access_cache.pop(auth_context.session.id, None)
    return True
