"""Project-related API endpoints."""

import asyncio
import logging

from fastapi import APIRouter, Depends

from app.core.gitlab_client import get_cached_projects as _get_cached_projects
from app.core.gitlab_client import get_gitlab_client
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/projects")
async def list_projects(
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List accessible GitLab projects.

    Returns:
        List of projects with id, name, and path
    """
    if not access_scope.is_unrestricted:
        return access_scope.accessible_projects
    try:
        return await _get_cached_projects()
    except Exception as exc:
        logger.warning("Failed to load accessible projects: %s", exc)
        gitlab = get_gitlab_client()
        return await asyncio.to_thread(gitlab.get_projects)


@router.get("/projects/{project_id}/branches")
async def list_branches(
    project_id: int,
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List branches for a GitLab project.

    Args:
        project_id: GitLab project ID

    Returns:
        List of branch names
    """
    require_project_access(project_id, access_scope)
    gitlab = get_gitlab_client()
    branches = await asyncio.to_thread(gitlab.get_branches, project_id)
    return branches
