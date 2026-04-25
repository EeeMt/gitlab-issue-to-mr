"""Runtime configuration API endpoints."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._validators import _is_valid_http_url, _sanitize_string_list
from app.config import Settings, get_effective_settings, get_runtime_config_types, get_settings
from app.core.config_crypto import ConfigEncryptionError
from app.core.worker_environment_variables import (
    list_worker_environment_variables,
    replace_worker_environment_variables,
    serialize_worker_environment_variable_for_runtime,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.runtime_config import (
    load_runtime_config_from_db,
    reset_all_runtime_config_overrides,
    reset_runtime_config_override,
    save_runtime_config_override,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class RuntimeWorkerEnvironmentVariableRequest(BaseModel):
    """One worker environment variable submitted via runtime config APIs."""

    key: str
    value: str
    is_secret: bool = False


class RuntimeWorkerEnvironmentVariableResponse(BaseModel):
    """One worker environment variable returned by runtime config APIs."""

    key: str
    value: str
    is_secret: bool
    value_configured: bool


class RuntimeConfigSection(BaseModel):
    """Runtime settings in the config response."""
    max_concurrency: int
    task_timeout: int
    scheduler_interval: int
    default_target_branch: str
    max_retries: int
    retry_delay: int
    alert_on_failure: bool
    alert_webhook_url_configured: bool
    anthropic_base_url: str
    anthropic_api_key_configured: bool
    anthropic_model: str
    claude_max_turns: int
    allow_monitor_for_users: bool
    allow_schedule_overview_for_users: bool
    allow_analytics_for_users: bool
    allow_oidc_diagnostics_for_users: bool
    worker_volume_mounts: str
    maven_cache_host_path: str
    maven_settings_host_path: str
    slot_max_tasks: int
    slot_max_tasks_enforce: bool
    worker_environment_variables: list[RuntimeWorkerEnvironmentVariableResponse] = Field(
        default_factory=list
    )


class RuntimeConfigUpdate(BaseModel):
    """Request model for updating runtime settings."""
    max_concurrency: Optional[int] = None
    task_timeout: Optional[int] = None
    scheduler_interval: Optional[int] = None
    default_target_branch: Optional[str] = None
    max_retries: Optional[int] = None
    retry_delay: Optional[int] = None
    alert_on_failure: Optional[bool] = None
    alert_webhook_url: Optional[str] = None
    clear_alert_webhook_url: bool = False
    anthropic_base_url: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    clear_anthropic_api_key: bool = False
    anthropic_model: Optional[str] = None
    claude_max_turns: Optional[int] = None
    allow_monitor_for_users: Optional[bool] = None
    allow_schedule_overview_for_users: Optional[bool] = None
    allow_analytics_for_users: Optional[bool] = None
    allow_oidc_diagnostics_for_users: Optional[bool] = None
    worker_volume_mounts: Optional[str] = None
    maven_cache_host_path: Optional[str] = None
    maven_settings_host_path: Optional[str] = None
    slot_max_tasks: Optional[int] = None
    slot_max_tasks_enforce: Optional[bool] = None
    worker_environment_variables: Optional[list[RuntimeWorkerEnvironmentVariableRequest]] = None


def _serialize_runtime_config(
    settings: Settings,
    worker_environment_variables: list[RuntimeWorkerEnvironmentVariableResponse] | None = None,
) -> RuntimeConfigSection:
    return RuntimeConfigSection(
        max_concurrency=settings.max_concurrency,
        task_timeout=settings.task_timeout,
        scheduler_interval=settings.scheduler_interval,
        default_target_branch=settings.default_target_branch,
        max_retries=settings.max_retries,
        retry_delay=settings.retry_delay,
        alert_on_failure=settings.alert_on_failure,
        alert_webhook_url_configured=bool(settings.alert_webhook_url),
        anthropic_base_url=settings.anthropic_base_url,
        anthropic_api_key_configured=bool(settings.anthropic_api_key),
        anthropic_model=settings.anthropic_model,
        claude_max_turns=settings.claude_max_turns,
        allow_monitor_for_users=settings.allow_monitor_for_users,
        allow_schedule_overview_for_users=settings.allow_schedule_overview_for_users,
        allow_analytics_for_users=settings.allow_analytics_for_users,
        allow_oidc_diagnostics_for_users=settings.allow_oidc_diagnostics_for_users,
        worker_volume_mounts=settings.worker_volume_mounts,
        maven_cache_host_path=settings.maven_cache_host_path,
        maven_settings_host_path=settings.maven_settings_host_path,
        slot_max_tasks=settings.slot_max_tasks,
        slot_max_tasks_enforce=settings.slot_max_tasks_enforce,
        worker_environment_variables=worker_environment_variables or [],
    )


async def _serialize_runtime_config_response(
    db: AsyncSession,
    settings: Settings | None = None,
) -> RuntimeConfigSection:
    """Serialize runtime config including persisted worker env vars."""
    rows = await list_worker_environment_variables(db)
    serialized_rows = [
        RuntimeWorkerEnvironmentVariableResponse.model_validate(
            serialize_worker_environment_variable_for_runtime(row)
        )
        for row in rows
    ]
    return _serialize_runtime_config(
        settings or get_effective_settings(),
        worker_environment_variables=serialized_rows,
    )


def _build_preview_settings(runtime_updates: dict[str, Any], base_settings: Settings) -> Settings:
    """Build a preview settings object with runtime updates applied."""
    settings_data = base_settings.model_dump()
    settings_data.update(runtime_updates)
    # Handle clear_* flags
    for key in list(settings_data.keys()):
        if key.startswith("clear_"):
            del settings_data[key]
    return Settings(**settings_data)


def _validate_config_value(key: str, value: object) -> object:
    """Validate a single configuration value."""
    if key == "max_concurrency":
        if not isinstance(value, int) or value < 1 or value > 20:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="max_concurrency must be between 1 and 20",
            )
        return value

    if key == "task_timeout":
        if not isinstance(value, int) or value < 60 or value > 7200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="task_timeout must be between 60 and 7200 seconds",
            )
        return value

    if key == "scheduler_interval":
        if not isinstance(value, int) or value < 1 or value > 60:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="scheduler_interval must be between 1 and 60 seconds",
            )
        return value

    if key == "default_target_branch":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="default_target_branch cannot be empty",
            )
        return value.strip()

    if key == "max_retries":
        if not isinstance(value, int) or value < 0 or value > 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="max_retries must be between 0 and 10",
            )
        return value

    if key == "retry_delay":
        if not isinstance(value, int) or value < 1 or value > 3600:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="retry_delay must be between 1 and 3600 seconds",
            )
        return value

    if key == "slot_max_tasks":
        if not isinstance(value, int) or value < 0 or value > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slot_max_tasks must be between 0 and 100",
            )
        return value

    if key in {"anthropic_base_url", "alert_webhook_url"}:
        if not isinstance(value, str) or not value.strip() or not _is_valid_http_url(value.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be a valid http/https URL",
            )
        return value.strip()

    if key == "anthropic_model":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="anthropic_model cannot be empty",
            )
        return value.strip()

    if key == "anthropic_api_key":
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="anthropic_api_key cannot be empty",
            )
        return value.strip()

    if key == "claude_max_turns":
        if not isinstance(value, int) or value < 1 or value > 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="claude_max_turns must be between 1 and 1000",
            )
        return value

    if key in {
        "alert_on_failure",
        "allow_monitor_for_users",
        "allow_schedule_overview_for_users",
        "allow_analytics_for_users",
        "allow_oidc_diagnostics_for_users",
        "slot_max_tasks_enforce",
    }:
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be a boolean",
            )
        return value

    return value


def _normalize_runtime_updates(raw_updates: dict[str, Any]) -> dict[str, Any]:
    """Normalize runtime config updates."""
    normalized: dict[str, Any] = {}
    for key, value in raw_updates.items():
        if key in {"clear_alert_webhook_url", "clear_anthropic_api_key"}:
            normalized[key] = bool(value)
            continue
        normalized[key] = _validate_config_value(key, value)
    return normalized


async def _sync_anthropic_to_default_provider(
    db: AsyncSession,
    updates: dict,
) -> None:
    """Sync anthropic_* runtime config changes to the default AI provider."""
    from app.models import AIProvider
    result = await db.execute(
        select(AIProvider).where(AIProvider.is_default == True)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        return

    changed = False
    if "anthropic_base_url" in updates:
        provider.base_url = updates["anthropic_base_url"]
        changed = True
    if "anthropic_model" in updates:
        provider.model = updates["anthropic_model"]
        changed = True
    if "claude_max_turns" in updates:
        provider.max_turns = int(updates["claude_max_turns"])
        changed = True
    if updates.get("clear_anthropic_api_key"):
        provider.api_key = None
        changed = True
    elif "anthropic_api_key" in updates:
        from app.core.config_crypto import encrypt_config_secret
        provider.api_key = encrypt_config_secret(updates["anthropic_api_key"])
        changed = True

    if changed:
        logger.info("Synced anthropic config changes to default AI provider")


@router.get("/config/runtime")
async def get_runtime_config(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Get current runtime configuration."""
    await load_runtime_config_from_db(db)
    return await _serialize_runtime_config_response(db)


async def apply_runtime_config_update(
    db: AsyncSession,
    runtime_update: RuntimeConfigUpdate,
    *,
    commit: bool,
) -> RuntimeConfigSection:
    """Apply runtime config updates and return the serialized runtime section."""
    await load_runtime_config_from_db(db)

    raw_runtime_updates = runtime_update.model_dump(
        exclude_unset=True,
        exclude={"worker_environment_variables"},
    )
    runtime_updates = _normalize_runtime_updates(raw_runtime_updates)
    worker_environment_variables_provided = (
        "worker_environment_variables" in runtime_update.model_fields_set
    )
    worker_environment_variables = runtime_update.worker_environment_variables

    clear_alert_webhook = bool(runtime_updates.pop("clear_alert_webhook_url", False))
    clear_anthropic_api_key = bool(runtime_updates.pop("clear_anthropic_api_key", False))

    provider_sync_updates = dict(runtime_updates)
    if clear_anthropic_api_key:
        provider_sync_updates["clear_anthropic_api_key"] = True

    if clear_alert_webhook and "alert_webhook_url" not in runtime_updates:
        runtime_updates["alert_webhook_url"] = get_settings().alert_webhook_url
    if clear_anthropic_api_key and "anthropic_api_key" not in runtime_updates:
        runtime_updates["anthropic_api_key"] = get_settings().anthropic_api_key

    try:
        for key, value in runtime_updates.items():
            await save_runtime_config_override(db, key, value)
            logger.info("Updated runtime config %s", key)

        if clear_alert_webhook and "alert_webhook_url" not in runtime_updates:
            await reset_runtime_config_override(db, "alert_webhook_url")
            logger.info("Cleared stored alert webhook URL")

        if clear_anthropic_api_key and "anthropic_api_key" not in runtime_updates:
            await reset_runtime_config_override(db, "anthropic_api_key")
            logger.info("Cleared stored Anthropic API key")
    except ConfigEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if worker_environment_variables_provided:
        if worker_environment_variables is None:
            logger.info("Ignored null runtime worker environment variables update")
        else:
            try:
                await replace_worker_environment_variables(
                    db,
                    worker_environment_variables,
                )
                logger.info("Replaced runtime worker environment variables")
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            except ConfigEncryptionError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(exc),
                ) from exc

    try:
        await load_runtime_config_from_db(db)
    except ConfigEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # Sync anthropic_* changes to default AI provider
    await _sync_anthropic_to_default_provider(db, provider_sync_updates)
    if commit:
        await db.commit()

    return await _serialize_runtime_config_response(db)


@router.patch("/config/runtime")
async def update_runtime_config(
    runtime_update: RuntimeConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Update persisted runtime configuration overrides."""
    return await apply_runtime_config_update(db, runtime_update, commit=True)


@router.delete("/config/runtime/{key}")
async def reset_runtime_config_key(
    key: str,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Reset one persisted runtime configuration override back to env/default value."""
    if key not in get_runtime_config_types():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown config key: {key}",
        )

    await reset_runtime_config_override(db, key)
    await load_runtime_config_from_db(db)
    logger.info("Reset persisted runtime configuration override for %s", key)
    return await _serialize_runtime_config_response(db)
