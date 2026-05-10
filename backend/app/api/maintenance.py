"""Admin maintenance API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.core.system_data_cleanup import cleanup_system_data
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import User


router = APIRouter()


class CleanupSystemDataRequest(BaseModel):
    older_than_days: int | None = Field(default=None, ge=1)
    force: bool = False


class CleanupSystemDataResponse(BaseModel):
    deleted_issues: int
    deleted_tasks: int
    skipped_active_issues: int
    skipped_active_tasks: int
    deleted_archives: int
    missing_archives: int
    deleted_workspaces: int
    container_cleanup_errors: list[dict[str, Any]]
    file_cleanup_errors: list[dict[str, Any]]


@router.post(
    "/config/maintenance/cleanup-system-data",
    response_model=CleanupSystemDataResponse,
)
async def cleanup_system_data_endpoint(
    body: CleanupSystemDataRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_admin_user),
) -> CleanupSystemDataResponse:
    settings = get_effective_settings()
    result = await cleanup_system_data(
        db,
        older_than_days=body.older_than_days,
        force=body.force,
        workspace_root=settings.worker_workspace_host_path,
    )
    return CleanupSystemDataResponse(**result.to_dict())
