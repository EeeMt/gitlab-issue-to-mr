"""Integration configuration API endpoints (GitLab, webhooks)."""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from gitlab.exceptions import GitlabError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._validators import _is_valid_http_url
from app.config import Settings, get_effective_settings
from app.core.gitlab_client import GitLabClient
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.runtime_config import load_runtime_config_from_db

logger = logging.getLogger(__name__)
router = APIRouter()


class IntegrationConfigSection(BaseModel):
    """Integration settings in the config response."""
    gitlab_url: str
    gitlab_bot_token_configured: bool
    gitlab_admin_token_configured: bool


class IntegrationConfigUpdate(BaseModel):
    """Request model for updating integration settings."""
    gitlab_url: str | None = None
    gitlab_bot_token: str | None = None
    clear_gitlab_bot_token: bool = False
    gitlab_admin_token: str | None = None
    clear_gitlab_admin_token: bool = False


class GitLabConfigTestRequest(BaseModel):
    integration: IntegrationConfigUpdate


class GitLabConfigTestResponse(BaseModel):
    server_version: str
    username: str
    gitlab_url: str


def _serialize_integration_config(settings: Settings) -> IntegrationConfigSection:
    return IntegrationConfigSection(
        gitlab_url=settings.gitlab_url,
        gitlab_bot_token_configured=bool(settings.gitlab_bot_token),
        gitlab_admin_token_configured=bool(settings.gitlab_admin_token),
    )


def _build_preview_settings_with_integration(
    integration_updates: dict,
    base_settings: Settings,
) -> Settings:
    """Build a preview settings object with integration updates applied."""
    settings_data = base_settings.model_dump()
    settings_data.update(integration_updates)
    # Handle clear_* flags
    for key in list(settings_data.keys()):
        if key.startswith("clear_"):
            del settings_data[key]
    return Settings(**settings_data)


def _normalize_integration_updates(raw_updates: dict) -> dict:
    """Normalize integration config updates."""
    normalized = {}
    for key, value in raw_updates.items():
        if key in {
            "clear_gitlab_bot_token",
            "clear_gitlab_admin_token",
        }:
            normalized[key] = bool(value)
            continue
        if key == "gitlab_url":
            if isinstance(value, str) and value.strip() and _is_valid_http_url(value.strip()):
                normalized[key] = value.strip()
        elif key in ("gitlab_bot_token", "gitlab_admin_token"):
            if isinstance(value, str) and value.strip():
                normalized[key] = value.strip()
    return normalized


def _validate_gitlab_integration(settings: Settings) -> None:
    """Validate GitLab integration settings."""
    if not settings.gitlab_url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="gitlab_url cannot be empty",
        )
    if not settings.gitlab_bot_token.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="gitlab_bot_token cannot be empty",
        )


@router.post("/config/gitlab/test", response_model=GitLabConfigTestResponse)
async def test_gitlab_config(
    request: GitLabConfigTestRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Validate GitLab connectivity with current or unsaved integration values."""
    await load_runtime_config_from_db(db)
    base_settings = get_effective_settings()
    integration_updates = _normalize_integration_updates(
        request.integration.model_dump(exclude_unset=True)
    )
    integration_updates.pop("clear_gitlab_bot_token", None)
    integration_updates.pop("clear_gitlab_admin_token", None)

    preview_settings = _build_preview_settings_with_integration(
        integration_updates, base_settings
    )
    _validate_gitlab_integration(preview_settings)

    client = GitLabClient(settings=preview_settings)
    try:
        version_payload = await asyncio.to_thread(client.gl.http_get, "/version")
        user_payload = await asyncio.to_thread(client.gl.http_get, "/user")
    except (GitlabError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitLab config test failed: {exc}",
        ) from exc
    finally:
        client.close()

    return GitLabConfigTestResponse(
        server_version=str(version_payload.get("version", "")),
        username=str(user_payload.get("username", "")),
        gitlab_url=preview_settings.gitlab_url,
    )


@router.post("/config/gitlab/projects/cache/invalidate")
async def invalidate_project_cache(
    _current_user=Depends(require_admin_user),
):
    """Invalidate the cached GitLab project list.

    Forces the next request to fetch a fresh project list from GitLab.
    """
    from app.core.gitlab_client import invalidate_project_list_cache
    from app.dependencies.project_access import invalidate_project_access_cache

    invalidate_project_list_cache()
    invalidate_project_access_cache()
    return {"status": "success", "message": "Project cache invalidated"}
