"""GitLab project webhook configuration API endpoints."""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from gitlab.exceptions import GitlabError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_effective_settings
from app.core.gitlab_client import GitLabClient
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.project_webhook_config import (
    get_project_webhook_secret,
    has_project_webhook_secret,
    save_project_webhook_secret,
)
from app.runtime_config import load_runtime_config_from_db

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_valid_http_url(value: str) -> bool:
    from urllib.parse import urlparse
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class GitLabProjectWebhookSetupResponse(BaseModel):
    action: str
    project_id: int
    project_name: str
    project_path_with_namespace: str
    webhook_url: str
    hook_id: int


class GitLabProjectWebhookStatusResponse(BaseModel):
    project_id: int
    project_name: str
    project_path_with_namespace: str
    target_webhook_url: str
    status: str
    status_detail: Optional[str] = None
    hook_found: bool
    hook_id: Optional[int] = None
    hook_url: Optional[str] = None
    note_events: Optional[bool] = None
    merge_requests_events: Optional[bool] = None
    enable_ssl_verification: Optional[bool] = None
    managed_secret_configured: bool
    global_secret_fallback_configured: bool
    secret_mode: str


def _build_gitlab_webhook_target_url(settings: Settings) -> str:
    backend_url = settings.backend_url.strip()
    if not backend_url or not _is_valid_http_url(backend_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="backend_url must be configured as a valid http/https URL before setting up GitLab webhooks.",
        )
    return f"{backend_url.rstrip('/')}/api/webhook/gitlab"


def _validate_gitlab_webhook_ready(settings: Settings) -> str:
    missing: list[str] = []
    if not settings.gitlab_url.strip():
        missing.append("gitlab_url")
    if not settings.gitlab_admin_token.strip():
        missing.append("gitlab_admin_token")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitLab webhook setup requires these configured fields: {', '.join(missing)}",
        )
    return _build_gitlab_webhook_target_url(settings)


def _build_gitlab_project_webhook_status_response(
    *,
    project_id: int,
    project_name: str,
    project_path_with_namespace: str,
    target_webhook_url: str,
    managed_secret_configured: bool,
    global_secret_fallback_configured: bool,
    matched_hook: Optional[dict[str, Any]] = None,
    inspection_error: Optional[str] = None,
) -> GitLabProjectWebhookStatusResponse:
    secret_mode = "project" if managed_secret_configured else "global_fallback" if global_secret_fallback_configured else "none"
    hook_found = matched_hook is not None
    note_events = bool(matched_hook.get("note_events")) if matched_hook is not None else None
    merge_requests_events = bool(matched_hook.get("merge_requests_events")) if matched_hook is not None else None
    enable_ssl_verification = bool(matched_hook.get("enable_ssl_verification")) if matched_hook is not None else None

    if inspection_error:
        status_value = "error"
        status_detail = inspection_error
    elif not hook_found:
        status_value = "missing"
        status_detail = "No webhook matches the configured callback URL"
    elif note_events and enable_ssl_verification and merge_requests_events:
        status_value = "configured"
        status_detail = None
    else:
        status_value = "needs_attention"
        issues: list[str] = []
        if not note_events:
            issues.append("note events disabled")
        if not enable_ssl_verification:
            issues.append("SSL verification disabled")
        if not merge_requests_events:
            issues.append("MR events disabled")
        status_detail = ", ".join(issues) if issues else "Webhook settings need attention"

    return GitLabProjectWebhookStatusResponse(
        project_id=project_id,
        project_name=project_name,
        project_path_with_namespace=project_path_with_namespace,
        target_webhook_url=target_webhook_url,
        status=status_value,
        status_detail=status_detail,
        hook_found=hook_found,
        hook_id=int(matched_hook["id"]) if matched_hook is not None else None,
        hook_url=str(matched_hook.get("url", "")) if matched_hook is not None else None,
        note_events=note_events,
        merge_requests_events=merge_requests_events,
        enable_ssl_verification=enable_ssl_verification,
        managed_secret_configured=managed_secret_configured,
        global_secret_fallback_configured=global_secret_fallback_configured,
        secret_mode=secret_mode,
    )


@router.post("/config/gitlab/projects/{project_id}/webhook", response_model=GitLabProjectWebhookSetupResponse)
async def setup_gitlab_project_webhook(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Create or update the GitLab webhook for one project."""
    await load_runtime_config_from_db(db)
    settings = get_effective_settings()
    webhook_url = _validate_gitlab_webhook_ready(settings)
    managed_secret = await get_project_webhook_secret(db, project_id)
    if not managed_secret:
        managed_secret = secrets.token_urlsafe(32)
        await save_project_webhook_secret(db, project_id, managed_secret)

    client = GitLabClient(settings=settings, private_token=settings.gitlab_admin_token)
    try:
        project = await asyncio.to_thread(client.get_project, project_id)
        result = await asyncio.to_thread(
            client.ensure_project_webhook,
            project_id,
            webhook_url,
            managed_secret,
        )
    except (GitlabError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitLab webhook setup failed: {exc}",
        ) from exc
    finally:
        client.close()

    hook_payload = result["hook"]
    return GitLabProjectWebhookSetupResponse(
        action=str(result["action"]),
        project_id=project_id,
        project_name=str(getattr(project, "name", "") or ""),
        project_path_with_namespace=str(getattr(project, "path_with_namespace", "") or ""),
        webhook_url=str(hook_payload.get("url", webhook_url)),
        hook_id=int(hook_payload["id"]),
    )


@router.get("/config/gitlab/projects/{project_id}/webhook", response_model=GitLabProjectWebhookStatusResponse)
async def get_gitlab_project_webhook_status(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Inspect the GitLab webhook status for one project."""
    await load_runtime_config_from_db(db)
    settings = get_effective_settings()
    target_webhook_url = _validate_gitlab_webhook_ready(settings)

    client = GitLabClient(settings=settings, private_token=settings.gitlab_admin_token)
    try:
        project = await asyncio.to_thread(client.get_project, project_id)
        hooks = await asyncio.to_thread(client.get_project_hooks, project_id)
    except (GitlabError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitLab webhook status lookup failed: {exc}",
        ) from exc
    finally:
        client.close()

    normalized_target = GitLabClient._normalize_hook_url(target_webhook_url)
    matched_hook = next(
        (
            hook for hook in hooks
            if GitLabClient._normalize_hook_url(str(hook.get("url", ""))) == normalized_target
        ),
        None,
    )

    return _build_gitlab_project_webhook_status_response(
        project_id=project_id,
        project_name=str(getattr(project, "name", "") or ""),
        project_path_with_namespace=str(getattr(project, "path_with_namespace", "") or ""),
        target_webhook_url=target_webhook_url,
        matched_hook=matched_hook,
        managed_secret_configured=await has_project_webhook_secret(db, project_id),
        global_secret_fallback_configured=bool(settings.gitlab_webhook_secret.strip()),
    )


@router.get("/config/gitlab/webhooks", response_model=list[GitLabProjectWebhookStatusResponse])
async def list_gitlab_project_webhook_statuses(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Inspect GitLab webhook status across all manageable projects."""
    await load_runtime_config_from_db(db)
    settings = get_effective_settings()
    target_webhook_url = _validate_gitlab_webhook_ready(settings)

    client = GitLabClient(settings=settings, private_token=settings.gitlab_admin_token)

    def collect_project_snapshots() -> list[dict[str, Any]]:
        projects = sorted(
            client.get_projects(),
            key=lambda project: str(project.get("path_with_namespace", "") or project.get("name", "")).lower(),
        )
        normalized_target = GitLabClient._normalize_hook_url(target_webhook_url)
        snapshots: list[dict[str, Any]] = []

        for project in projects:
            project_id = int(project["id"])
            inspection_error: Optional[str] = None
            matched_hook: Optional[dict[str, Any]] = None

            try:
                hooks = client.get_project_hooks(project_id)
                matched_hook = next(
                    (
                        hook for hook in hooks
                        if GitLabClient._normalize_hook_url(str(hook.get("url", ""))) == normalized_target
                    ),
                    None,
                )
            except (GitlabError, httpx.HTTPError) as exc:
                inspection_error = str(exc)

            snapshots.append({
                "project_id": project_id,
                "project_name": str(project.get("name", "") or ""),
                "project_path_with_namespace": str(project.get("path_with_namespace", "") or ""),
                "matched_hook": matched_hook,
                "inspection_error": inspection_error,
            })

        return snapshots

    try:
        snapshots = await asyncio.to_thread(collect_project_snapshots)
    except (GitlabError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitLab webhook status lookup failed: {exc}",
        ) from exc
    finally:
        client.close()

    statuses: list[GitLabProjectWebhookStatusResponse] = []
    global_secret_fallback_configured = bool(settings.gitlab_webhook_secret.strip())

    for snapshot in snapshots:
        statuses.append(
            _build_gitlab_project_webhook_status_response(
                project_id=int(snapshot["project_id"]),
                project_name=str(snapshot["project_name"]),
                project_path_with_namespace=str(snapshot["project_path_with_namespace"]),
                target_webhook_url=target_webhook_url,
                matched_hook=snapshot["matched_hook"],
                inspection_error=snapshot["inspection_error"],
                managed_secret_configured=await has_project_webhook_secret(db, int(snapshot["project_id"])),
                global_secret_fallback_configured=global_secret_fallback_configured,
            )
        )

    return statuses
