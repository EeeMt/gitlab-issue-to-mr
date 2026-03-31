"""Shared project utilities."""

import logging
from typing import Any, Optional

from app.core.gitlab_client import get_cached_projects

logger = logging.getLogger(__name__)


def _projects_to_lookup(projects: list[dict[str, Any]]) -> dict[int, dict[str, Optional[str]]]:
    """Convert a list of project dicts to a lookup keyed by project ID.

    Args:
        projects: List of project dictionaries from GitLab API

    Returns:
        Dict mapping project ID to metadata dict with 'project_name' and 'project_path_with_namespace'
    """
    return {
        int(project["id"]): {
            "project_name": project.get("name"),
            "project_path_with_namespace": project.get("path_with_namespace"),
        }
        for project in projects
    }


async def build_project_lookup(
    accessible_projects: Optional[list[dict[str, Any]]] = None,
    is_unrestricted: bool = True,
) -> dict[int, dict[str, Optional[str]]]:
    """Build a project metadata lookup keyed by GitLab project ID.

    Args:
        accessible_projects: List of accessible projects (for restricted access)
        is_unrestricted: Whether the user has unrestricted project access

    Returns:
        Dict mapping project ID to metadata dict
    """
    if not is_unrestricted:
        return _projects_to_lookup(accessible_projects or [])

    try:
        return _projects_to_lookup(await get_cached_projects())
    except Exception as exc:
        logger.warning(f"Failed to load project metadata: {exc}")
        return {}


async def get_project_metadata(project_id: int) -> dict[str, Optional[str]]:
    """Get project metadata for a single project ID.

    Args:
        project_id: GitLab project ID

    Returns:
        Dict with 'project_name' and 'project_path_with_namespace'
    """
    try:
        projects = await get_cached_projects()
        project = next((p for p in projects if int(p["id"]) == project_id), None)
        if project:
            return {
                "project_name": project.get("name"),
                "project_path_with_namespace": project.get("path_with_namespace"),
            }
    except Exception as exc:
        logger.warning(f"Failed to load project {project_id} metadata: {exc}")

    return {
        "project_name": None,
        "project_path_with_namespace": None,
    }
