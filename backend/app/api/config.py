"""Configuration API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings, get_runtime_config_types
from app.database import get_db
from app.runtime_config import (
    load_runtime_config_from_db,
    reset_all_runtime_config_overrides,
    reset_runtime_config_override,
    save_runtime_config_override,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ConfigUpdate(BaseModel):
    """Configuration update request."""

    max_concurrency: Optional[int] = None
    task_timeout: Optional[int] = None
    scheduler_interval: Optional[int] = None
    default_target_branch: Optional[str] = None


def _serialize_effective_config() -> dict:
    settings = get_effective_settings()
    return {
        "max_concurrency": settings.max_concurrency,
        "task_timeout": settings.task_timeout,
        "scheduler_interval": settings.scheduler_interval,
        "default_target_branch": settings.default_target_branch,
    }


def _validate_config_value(key: str, value: object) -> None:
    if key == "max_concurrency" and (not isinstance(value, int) or value < 1 or value > 20):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="max_concurrency must be between 1 and 20",
        )

    if key == "task_timeout" and (not isinstance(value, int) or value < 60 or value > 7200):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task_timeout must be between 60 and 7200 seconds",
        )

    if key == "scheduler_interval" and (not isinstance(value, int) or value < 1 or value > 60):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scheduler_interval must be between 1 and 60 seconds",
        )

    if key == "default_target_branch" and (not isinstance(value, str) or not value.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_target_branch cannot be empty",
        )


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    """Get current configuration."""
    await load_runtime_config_from_db(db)
    return _serialize_effective_config()


@router.patch("/config")
async def update_config(
    config_update: ConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update persisted runtime configuration overrides."""
    updates = config_update.model_dump(exclude_unset=True)

    for key, value in updates.items():
        _validate_config_value(key, value)
        if key == "default_target_branch":
            value = value.strip()
        await save_runtime_config_override(db, key, value)
        logger.info("Updated runtime config %s to %s", key, value)

    await load_runtime_config_from_db(db)
    return _serialize_effective_config()


@router.post("/config/reset")
async def reset_config(db: AsyncSession = Depends(get_db)):
    """Reset all runtime configuration overrides back to env/default values."""
    await reset_all_runtime_config_overrides(db)
    await load_runtime_config_from_db(db)
    logger.info("Reset all runtime configuration overrides")
    return _serialize_effective_config()


@router.delete("/config/{key}")
async def reset_config_key(key: str, db: AsyncSession = Depends(get_db)):
    """Reset one runtime configuration override back to env/default value."""
    if key not in get_runtime_config_types():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown config key: {key}",
        )

    await reset_runtime_config_override(db, key)
    await load_runtime_config_from_db(db)
    logger.info("Reset runtime configuration override for %s", key)
    return _serialize_effective_config()
