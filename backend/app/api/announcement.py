"""Announcement API endpoint - returns current system announcement."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import get_effective_settings
from app.dependencies.auth import require_authenticated_user

router = APIRouter()


class AnnouncementResponse(BaseModel):
    """System announcement response."""
    enabled: bool
    text: str
    level: str  # info | warning | error | success


@router.get("/announcement")
async def get_announcement(
    _current_user=Depends(require_authenticated_user),
) -> AnnouncementResponse:
    """Get the current system announcement. Available to all authenticated users."""
    settings = get_effective_settings()
    return AnnouncementResponse(
        enabled=settings.announcement_enabled,
        text=settings.announcement_text,
        level=settings.announcement_level,
    )
