"""Helpers for resolving GitLab project-scoped access for dashboard users."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from fastapi import Depends, HTTPException, status

from app.config import get_effective_settings
from app.core.gitlab_client import get_accessible_projects_for_oauth_token
from app.dependencies.auth import AuthContext, require_authenticated_context

_ACCESS_CACHE_TTL_SECONDS = 60
_project_access_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}


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
) -> ProjectAccessScope:
    """Resolve the set of GitLab projects the current user may access."""
    settings = get_effective_settings()
    if not settings.oidc_enabled or auth_context is None:
        return ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    if auth_context.user.platform_role == "platform_admin":
        return ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    if not auth_context.gitlab_access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is missing GitLab API access. Please sign in again.",
        )

    cache_entry = _project_access_cache.get(auth_context.user.id)
    now = time.time()
    if cache_entry and cache_entry[0] > now:
        projects = cache_entry[1]
    else:
        try:
            projects = await get_accessible_projects_for_oauth_token(auth_context.gitlab_access_token)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="GitLab access token is no longer valid. Please sign in again.",
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
        _project_access_cache[auth_context.user.id] = (now + _ACCESS_CACHE_TTL_SECONDS, projects)

    return ProjectAccessScope(is_unrestricted=False, accessible_projects=projects)


def require_project_access(project_id: int, scope: ProjectAccessScope) -> None:
    """Enforce access to a specific GitLab project."""
    if scope.allows(project_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Project {project_id} is not accessible for the current user",
    )
