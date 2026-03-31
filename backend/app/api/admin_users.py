"""Admin-only user management endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import revoke_user_sessions
from app.core.user_roles import (
    PLATFORM_ROLE_ADMIN,
    ROLE_SOURCE_MANUAL,
    VALID_PLATFORM_ROLES,
    VALID_USER_STATES,
    USER_STATE_DISABLED,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import User, UserSession

router = APIRouter()


class AdminUserSummary(BaseModel):
    id: int
    gitlab_user_id: Optional[int]
    username: str
    display_name: Optional[str]
    email: Optional[str]
    avatar_url: Optional[str]
    platform_role: str
    platform_role_source: str
    state: str
    last_login_at: Optional[datetime]
    created_at: datetime
    active_session_count: int
    last_session_seen_at: Optional[datetime]
    is_current_user: bool


class AdminUserUpdateRequest(BaseModel):
    platform_role: Optional[str] = None
    state: Optional[str] = None


class RevokeUserSessionsResponse(BaseModel):
    status: str
    revoked_count: int


def _serialize_admin_user(
    user: User,
    *,
    active_session_count: int,
    last_session_seen_at: Optional[datetime],
    current_user_id: int,
) -> AdminUserSummary:
    return AdminUserSummary(
        id=user.id,
        gitlab_user_id=user.gitlab_user_id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        avatar_url=user.avatar_url,
        platform_role=user.platform_role,
        platform_role_source=user.platform_role_source,
        state=user.state,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        active_session_count=active_session_count,
        last_session_seen_at=last_session_seen_at,
        is_current_user=user.id == current_user_id,
    )


async def _count_other_active_admins(db: AsyncSession, exclude_user_id: int) -> int:
    result = await db.execute(
        select(func.count(User.id)).where(
            User.id != exclude_user_id,
            User.platform_role == PLATFORM_ROLE_ADMIN,
            User.state == "active",
        )
    )
    return int(result.scalar_one())


@router.get("/admin/users", response_model=list[AdminUserSummary])
async def list_admin_users(
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List dashboard users with their current access state and session summary."""
    now = datetime.now(UTC)
    active_sessions = (
        select(
            UserSession.user_id.label("user_id"),
            func.count(UserSession.id).label("active_session_count"),
            func.max(UserSession.last_seen_at).label("last_session_seen_at"),
        )
        .where(
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .group_by(UserSession.user_id)
        .subquery()
    )

    result = await db.execute(
        select(
            User,
            func.coalesce(active_sessions.c.active_session_count, 0),
            active_sessions.c.last_session_seen_at,
        )
        .outerjoin(active_sessions, active_sessions.c.user_id == User.id)
        .order_by(
            case((User.platform_role == PLATFORM_ROLE_ADMIN, 0), else_=1),
            case((User.state == "active", 0), else_=1),
            User.last_login_at.desc().nullslast(),
            User.created_at.desc(),
        )
    )

    return [
        _serialize_admin_user(
            user,
            active_session_count=int(active_session_count or 0),
            last_session_seen_at=last_session_seen_at,
            current_user_id=current_user.id,
        )
        for user, active_session_count, last_session_seen_at in result.all()
    ]


@router.patch("/admin/users/{user_id}", response_model=AdminUserSummary)
async def update_admin_user(
    user_id: int,
    payload: AdminUserUpdateRequest,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a dashboard user's explicit role or active state."""
    if payload.platform_role is None and payload.state is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be updated",
        )

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role or state from this screen",
        )

    if payload.platform_role is not None and payload.platform_role not in VALID_PLATFORM_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="platform_role must be platform_admin or platform_user",
        )

    if payload.state is not None and payload.state not in VALID_USER_STATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state must be active or disabled",
        )

    next_role = payload.platform_role or user.platform_role
    next_state = payload.state or user.state
    removing_admin_access = user.platform_role == PLATFORM_ROLE_ADMIN and (
        next_role != PLATFORM_ROLE_ADMIN or next_state != "active"
    )
    if removing_admin_access and await _count_other_active_admins(db, exclude_user_id=user.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the last active platform admin",
        )

    if payload.platform_role is not None:
        user.platform_role = payload.platform_role
        user.platform_role_source = ROLE_SOURCE_MANUAL

    if payload.state is not None:
        user.state = payload.state

    if user.state == USER_STATE_DISABLED:
        await revoke_user_sessions(db, user.id)

    await db.flush()
    await db.commit()
    await db.refresh(user)

    active_count_result = await db.execute(
        select(
            func.count(UserSession.id),
            func.max(UserSession.last_seen_at),
        ).where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
        )
    )
    active_session_count, last_session_seen_at = active_count_result.one()
    return _serialize_admin_user(
        user,
        active_session_count=int(active_session_count or 0),
        last_session_seen_at=last_session_seen_at,
        current_user_id=current_user.id,
    )


@router.post("/admin/users/{user_id}/sessions/revoke", response_model=RevokeUserSessionsResponse)
async def revoke_admin_user_sessions(
    user_id: int,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke all active sessions for a dashboard user."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use the normal logout flow for your own current session",
        )

    revoked_count = await revoke_user_sessions(db, user.id)
    await db.commit()
    return RevokeUserSessionsResponse(status="success", revoked_count=revoked_count)
