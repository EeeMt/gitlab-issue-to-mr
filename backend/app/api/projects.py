"""Project-related API endpoints."""

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from gitlab.exceptions import GitlabError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.project_webhooks import (
    _build_gitlab_project_webhook_status_response,
    _validate_gitlab_webhook_ready,
    get_ci_auto_repair_webhook_issues,
)
from app.config import get_effective_settings
from app.core.gitlab_client import (
    GitLabClient,
    get_gitlab_client,
)
from app.core.gitlab_client import (
    get_cached_projects as _get_cached_projects,
)
from app.database import get_db
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.project_webhook_config import has_project_webhook_secret
from app.runtime_config import load_runtime_config_from_db

logger = logging.getLogger(__name__)
router = APIRouter()


class ProjectCIAutoRepairAvailabilityResponse(BaseModel):
    project_id: int
    webhook_status: str
    webhook_status_issues: list[str]
    ci_auto_repair_available: bool


def _unavailable_webhook_status(
    project_id: int,
) -> ProjectCIAutoRepairAvailabilityResponse:
    return ProjectCIAutoRepairAvailabilityResponse(
        project_id=project_id,
        webhook_status="error",
        webhook_status_issues=["webhook_status_unavailable"],
        ci_auto_repair_available=False,
    )


async def _get_project_ci_auto_repair_availability(
    project_id: int,
    db: AsyncSession,
) -> ProjectCIAutoRepairAvailabilityResponse:
    await load_runtime_config_from_db(db)
    settings = get_effective_settings()
    try:
        target_webhook_url = _validate_gitlab_webhook_ready(settings)
    except HTTPException:
        return _unavailable_webhook_status(project_id)

    managed_secret_configured = await has_project_webhook_secret(db, project_id)
    # Release the request transaction before waiting on the external GitLab API.
    await db.commit()

    client = GitLabClient(settings=settings, private_token=settings.gitlab_admin_token)
    try:
        hooks = await asyncio.to_thread(client.get_project_hooks, project_id)
    except (GitlabError, httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        logger.warning(
            "Failed to inspect webhook status for project %s: %s",
            project_id,
            exc,
        )
        return _unavailable_webhook_status(project_id)
    finally:
        client.close()

    normalized_target = GitLabClient._normalize_hook_url(target_webhook_url)
    matched_hook = next(
        (
            hook
            for hook in hooks
            if GitLabClient._normalize_hook_url(str(hook.get("url", "")))
            == normalized_target
        ),
        None,
    )
    status_response = _build_gitlab_project_webhook_status_response(
        project_id=project_id,
        project_name="",
        project_path_with_namespace="",
        target_webhook_url=target_webhook_url,
        matched_hook=matched_hook,
        managed_secret_configured=managed_secret_configured,
    )
    issues = get_ci_auto_repair_webhook_issues(status_response)
    webhook_status = status_response.status
    if issues and status_response.hook_found and webhook_status == "configured":
        webhook_status = "needs_attention"
    return ProjectCIAutoRepairAvailabilityResponse(
        project_id=project_id,
        webhook_status=webhook_status,
        webhook_status_issues=issues,
        ci_auto_repair_available=not issues,
    )


@router.get("/projects")
async def list_projects(
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List accessible GitLab projects.

    Returns:
        List of projects with id, name, and path
    """
    if not access_scope.is_unrestricted:
        projects = access_scope.accessible_projects
    else:
        try:
            projects = await _get_cached_projects()
        except Exception as exc:
            logger.warning("Failed to load accessible projects: %s", exc)
            gitlab = get_gitlab_client()
            projects = await asyncio.to_thread(gitlab.get_projects)

    return projects


@router.get(
    "/projects/{project_id}/ci-auto-repair-availability",
    response_model=ProjectCIAutoRepairAvailabilityResponse,
)
async def get_project_ci_auto_repair_availability(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Return whether one project's webhook supports CI auto-repair."""
    require_project_access(project_id, access_scope)
    return await _get_project_ci_auto_repair_availability(project_id, db)


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
