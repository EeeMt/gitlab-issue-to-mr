"""Configuration API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import get_effective_settings, get_runtime_config, update_runtime_config

logger = logging.getLogger(__name__)
router = APIRouter()


class ConfigUpdate(BaseModel):
    """Configuration update request."""

    max_concurrency: Optional[int] = None
    task_timeout: Optional[int] = None
    scheduler_interval: Optional[int] = None
    default_target_branch: Optional[str] = None


@router.get("/config")
async def get_config():
    """Get current configuration.

    Returns:
        Configuration object
    """
    settings = get_effective_settings()
    runtime = get_runtime_config()

    return {
        "max_concurrency": runtime.get("max_concurrency", settings.max_concurrency),
        "task_timeout": runtime.get("task_timeout", settings.task_timeout),
        "scheduler_interval": runtime.get("scheduler_interval", settings.scheduler_interval),
        "default_target_branch": runtime.get("default_target_branch", settings.default_target_branch),
    }


@router.patch("/config")
async def update_config(config_update: ConfigUpdate):
    """Update runtime configuration.

    Args:
        config_update: Configuration updates

    Returns:
        Updated configuration
    """
    runtime = get_runtime_config()

    if config_update.max_concurrency is not None:
        if config_update.max_concurrency < 1 or config_update.max_concurrency > 20:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="max_concurrency must be between 1 and 20",
            )
        update_runtime_config("max_concurrency", config_update.max_concurrency)
        logger.info(f"Updated max_concurrency to {config_update.max_concurrency}")

    if config_update.task_timeout is not None:
        if config_update.task_timeout < 60 or config_update.task_timeout > 7200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="task_timeout must be between 60 and 7200 seconds",
            )
        update_runtime_config("task_timeout", config_update.task_timeout)
        logger.info(f"Updated task_timeout to {config_update.task_timeout}")

    if config_update.scheduler_interval is not None:
        if config_update.scheduler_interval < 1 or config_update.scheduler_interval > 60:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="scheduler_interval must be between 1 and 60 seconds",
            )
        update_runtime_config("scheduler_interval", config_update.scheduler_interval)
        logger.info(f"Updated scheduler_interval to {config_update.scheduler_interval}")

    if config_update.default_target_branch is not None:
        if not config_update.default_target_branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="default_target_branch cannot be empty",
            )
        update_runtime_config("default_target_branch", config_update.default_target_branch)
        logger.info(f"Updated default_target_branch to {config_update.default_target_branch}")

    # Return current config
    settings = get_effective_settings()
    runtime = get_runtime_config()
    return {
        "max_concurrency": runtime.get("max_concurrency", settings.max_concurrency),
        "task_timeout": runtime.get("task_timeout", settings.task_timeout),
        "scheduler_interval": runtime.get("scheduler_interval", settings.scheduler_interval),
        "default_target_branch": runtime.get("default_target_branch", settings.default_target_branch),
    }
