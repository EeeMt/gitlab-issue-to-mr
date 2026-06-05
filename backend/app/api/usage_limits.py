"""Usage limit API endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.usage_limits import UsageQuotaService, _next_reset_timestamps
from app.database import get_db
from app.dependencies.auth import require_admin_user, require_authenticated_user
from app.models import UsageLimitPolicy, User

router = APIRouter()


class DefaultUsageLimitItemInput(BaseModel):
    mode: Literal["custom", "unlimited"]
    value: int | None = None

    @model_validator(mode="after")
    def validate_value(self) -> DefaultUsageLimitItemInput:
        self.value = _normalize_policy_value(self.mode, self.value, allow_inherit=False)
        return self


class UserUsageLimitItemInput(BaseModel):
    mode: Literal["inherit", "custom", "unlimited"]
    value: int | None = None

    @model_validator(mode="after")
    def validate_value(self) -> UserUsageLimitItemInput:
        self.value = _normalize_policy_value(self.mode, self.value, allow_inherit=True)
        return self


class AdminUsageLimitDefaultUpdateRequest(BaseModel):
    daily_tokens: DefaultUsageLimitItemInput
    weekly_tokens: DefaultUsageLimitItemInput
    daily_tasks: DefaultUsageLimitItemInput
    weekly_tasks: DefaultUsageLimitItemInput


class AdminUsageLimitUserUpdateRequest(BaseModel):
    daily_tokens: UserUsageLimitItemInput
    weekly_tokens: UserUsageLimitItemInput
    daily_tasks: UserUsageLimitItemInput
    weekly_tasks: UserUsageLimitItemInput


@router.get("/usage/me")
async def get_my_usage_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    return await build_current_user_usage_summary(db, current_user)


@router.get("/admin/usage-limits/users")
async def list_admin_usage_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    return await list_usage_limit_users(db)


@router.get("/admin/usage-limits/default")
async def get_admin_usage_limit_default_route(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    return await get_admin_usage_limit_default(db)


@router.patch("/admin/usage-limits/default")
async def update_admin_usage_limit_default_route(
    payload: AdminUsageLimitDefaultUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    return await update_admin_usage_limit_default(db, payload)


@router.patch("/admin/usage-limits/users/{user_id}")
async def update_admin_usage_user(
    user_id: int,
    payload: AdminUsageLimitUserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    return await update_usage_limit_user(db, user_id, payload)


async def build_current_user_usage_summary(
    db: AsyncSession,
    current_user: User,
    *,
    now=None,
) -> dict:
    quota_service = get_usage_quota_service()
    current_time = now or current_user_summary_now()
    usage = await quota_service.get_current_usage_totals(db, current_user.id, now=current_time)
    limits = await quota_service.resolve_effective_limits(db, current_user.id)
    serialized_limits = {
        field: {"mode": limit.mode, "value": limit.value}
        for field, limit in limits.items()
    }
    reset_at = _next_reset_timestamps(current_time)
    is_over_limit = any(
        not limit.is_unlimited and limit.value is not None and usage.get(field, 0) > limit.value
        for field, limit in limits.items()
    )
    near_limit = any(
        not limit.is_unlimited
        and limit.value not in (None, 0)
        and usage.get(field, 0) / limit.value >= 0.8
        for field, limit in limits.items()
    )
    severity = "over_limit" if is_over_limit else "near_limit" if near_limit else "normal"
    return {
        "user_id": current_user.id,
        "usage": usage,
        "limits": serialized_limits,
        "reset_at": reset_at,
        "is_over_limit": is_over_limit,
        "severity": severity,
    }


async def list_usage_limit_users(db: AsyncSession, *, now=None) -> list[dict]:
    return await _list_usage_limit_users(db, now=now)


async def get_admin_usage_limit_default(db: AsyncSession) -> dict:
    result = await db.execute(
        select(UsageLimitPolicy).where(
            UsageLimitPolicy.scope_type == "system_default",
            UsageLimitPolicy.user_id.is_(None),
        )
    )
    policy = result.scalar_one_or_none()
    return _serialize_policy(policy, allow_inherit=False)


async def update_admin_usage_limit_default(db: AsyncSession, payload: dict) -> dict:
    result = await db.execute(
        select(UsageLimitPolicy).where(
            UsageLimitPolicy.scope_type == "system_default",
            UsageLimitPolicy.user_id.is_(None),
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        policy = UsageLimitPolicy(scope_type="system_default", user_id=None)
        db.add(policy)
    _apply_policy_payload(policy, payload, allow_inherit=False)
    return _serialize_policy(policy, allow_inherit=False)


async def update_usage_limit_user(db: AsyncSession, user_id: int, payload: dict, *, now=None) -> dict:
    return await _update_usage_limit_user(db, user_id, payload, now=now)


def get_usage_quota_service() -> UsageQuotaService:
    return UsageQuotaService()


def current_user_summary_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _serialize_policy(policy: UsageLimitPolicy | None, *, allow_inherit: bool) -> dict:
    default_mode = "inherit" if allow_inherit else "unlimited"
    return {
        field: {
            "mode": getattr(policy, f"{field}_mode", default_mode),
            "value": getattr(policy, f"{field}_value", None),
        }
        for field in ("daily_tokens", "weekly_tokens", "daily_tasks", "weekly_tasks")
    }


def _apply_policy_payload(policy: UsageLimitPolicy, payload: dict, *, allow_inherit: bool) -> None:
    payload_data = payload.model_dump() if isinstance(payload, BaseModel) else payload
    valid_modes = {"custom", "unlimited"} | ({"inherit"} if allow_inherit else set())
    for field in ("daily_tokens", "weekly_tokens", "daily_tasks", "weekly_tasks"):
        item = payload_data[field]
        mode = item["mode"]
        if mode not in valid_modes:
            raise HTTPException(status_code=422, detail=f"Invalid mode for {field}: {mode}")
        setattr(policy, f"{field}_mode", mode)
        setattr(
            policy,
            f"{field}_value",
            _normalize_policy_value(mode, item.get("value"), allow_inherit=allow_inherit),
        )


async def _list_usage_limit_users(db: AsyncSession, *, now=None) -> list[dict]:
    result = await db.execute(select(User).order_by(User.username))
    users = result.scalars().all()
    return [await _build_admin_usage_limit_user_row(db, user, now=now) for user in users]


async def _update_usage_limit_user(db: AsyncSession, user_id: int, payload: dict, *, now=None) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    result = await db.execute(
        select(UsageLimitPolicy).where(
            UsageLimitPolicy.scope_type == "user",
            UsageLimitPolicy.user_id == user_id,
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        policy = UsageLimitPolicy(scope_type="user", user_id=user_id)
        db.add(policy)
    _apply_policy_payload(policy, payload, allow_inherit=True)
    return await _build_admin_usage_limit_user_row(db, user, policy=policy, now=now)


async def _build_admin_usage_limit_user_row(
    db: AsyncSession,
    user: User,
    *,
    policy: UsageLimitPolicy | None = None,
    now=None,
) -> dict:
    quota_service = get_usage_quota_service()
    current_time = now or current_user_summary_now()
    user_policy = policy or await _load_user_policy(db, user.id)
    usage = await quota_service.get_current_usage_totals(db, user.id, now=current_time)
    limits = await quota_service.resolve_effective_limits(db, user.id, user_row=user_policy)
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "usage": usage,
        "limits": {
            field: {"mode": limit.mode, "value": limit.value}
            for field, limit in limits.items()
        },
        "overrides": _serialize_policy(user_policy, allow_inherit=True),
        "reset_at": _next_reset_timestamps(current_time),
    }


async def _load_user_policy(db: AsyncSession, user_id: int) -> UsageLimitPolicy | None:
    result = await db.execute(
        select(UsageLimitPolicy).where(
            UsageLimitPolicy.scope_type == "user",
            UsageLimitPolicy.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def _normalize_policy_value(mode: str, value: int | None, *, allow_inherit: bool) -> int | None:
    valid_modes = {"custom", "unlimited"} | ({"inherit"} if allow_inherit else set())
    if mode not in valid_modes:
        raise HTTPException(status_code=422, detail=f"Invalid mode: {mode}")
    if mode == "custom":
        if value is None or value <= 0:
            raise ValueError("Custom quota mode requires a positive numeric value")
        return value
    return None
