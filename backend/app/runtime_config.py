"""Runtime configuration persistence helpers."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    RuntimeConfigValue,
    get_secret_config_keys,
    get_runtime_config_types,
    reset_runtime_config,
    set_runtime_config,
    update_runtime_config,
)
from app.core.config_crypto import (
    ConfigEncryptionError,
    decrypt_config_secret,
    encrypt_config_secret,
)
from app.database import AsyncSessionLocal
from app.models import SystemConfig, WorkerEnvironmentVariable

logger = logging.getLogger(__name__)
_runtime_config_last_check_monotonic = 0.0
_runtime_config_last_signature: tuple[int, datetime | None] | None = None


def reset_runtime_config_sync_state() -> None:
    """Reset in-process refresh bookkeeping.

    Useful in tests and when a process deliberately wants to forget its last
    refresh checkpoint.
    """
    global _runtime_config_last_check_monotonic, _runtime_config_last_signature
    _runtime_config_last_check_monotonic = 0.0
    _runtime_config_last_signature = None


def _mark_runtime_config_synced(signature: tuple[int, datetime | None]) -> None:
    """Record the last observed runtime-config table signature for this process."""
    global _runtime_config_last_check_monotonic, _runtime_config_last_signature
    _runtime_config_last_check_monotonic = time.monotonic()
    _runtime_config_last_signature = signature


def _serialize_runtime_value(key: str, value: RuntimeConfigValue) -> tuple[str, str]:
    if key in get_secret_config_keys():
        return encrypt_config_secret(str(value)), "secret_str"

    expected_type = get_runtime_config_types()[key]
    if expected_type is int:
        return str(int(value)), "int"
    if expected_type is bool:
        return ("true" if value else "false"), "bool"
    return str(value), "str"


def _deserialize_runtime_value(key: str, raw_value: str, value_type: str) -> RuntimeConfigValue:
    if key in get_secret_config_keys():
        return decrypt_config_secret(raw_value)

    expected_type = get_runtime_config_types()[key]

    if expected_type is int or value_type == "int":
        return int(raw_value)
    if expected_type is bool or value_type == "bool":
        return raw_value.lower() in {"1", "true", "yes", "on"}
    return raw_value


async def load_runtime_config_from_db(db: Optional[AsyncSession] = None) -> dict[str, RuntimeConfigValue]:
    """Load runtime configuration overrides from the database into process memory."""
    owns_session = db is None
    if owns_session:
        async with AsyncSessionLocal() as session:
            return await load_runtime_config_from_db(session)

    result = await db.execute(select(SystemConfig))
    rows = result.scalars().all()
    overrides: dict[str, RuntimeConfigValue] = {}
    supported_keys = get_runtime_config_types()

    for row in rows:
        if row.key not in supported_keys:
            logger.warning("Ignoring unsupported system config key: %s", row.key)
            continue
        try:
            overrides[row.key] = _deserialize_runtime_value(row.key, row.value, row.value_type)
        except (ConfigEncryptionError, TypeError, ValueError) as exc:
            logger.warning("Ignoring invalid system config value for %s: %s", row.key, exc)

    set_runtime_config(overrides)
    latest_update = max((row.updated_at for row in rows if row.updated_at is not None), default=None)
    _mark_runtime_config_synced((len(rows), latest_update))
    return overrides


async def refresh_runtime_config_if_stale(
    db: Optional[AsyncSession] = None,
    *,
    min_check_interval: float = 1.0,
) -> bool:
    """Refresh process-local runtime config when the persisted config changed.

    Every worker keeps runtime overrides in local memory. This helper lets a
    worker cheaply poll a compact ``system_config`` signature and only perform
    a full reload when another process has changed the persisted config.
    """
    owns_session = db is None
    if owns_session:
        async with AsyncSessionLocal() as session:
            return await refresh_runtime_config_if_stale(
                session,
                min_check_interval=min_check_interval,
            )

    if (
        _runtime_config_last_check_monotonic
        and time.monotonic() - _runtime_config_last_check_monotonic < min_check_interval
    ):
        return False

    result = await db.execute(select(func.count(SystemConfig.key), func.max(SystemConfig.updated_at)))
    row_count, latest_update = result.one()
    signature = (int(row_count or 0), latest_update)
    if _runtime_config_last_check_monotonic and signature == _runtime_config_last_signature:
        _mark_runtime_config_synced(signature)
        return False

    await load_runtime_config_from_db(db)
    return True


async def save_runtime_config_override(
    db: AsyncSession,
    key: str,
    value: RuntimeConfigValue,
) -> None:
    """Persist one runtime configuration override."""
    serialized_value, value_type = _serialize_runtime_value(key, value)
    existing = await db.get(SystemConfig, key)
    if existing is None:
        db.add(SystemConfig(key=key, value=serialized_value, value_type=value_type))
    else:
        existing.value = serialized_value
        existing.value_type = value_type

    await db.flush()
    update_runtime_config(key, value)


async def reset_runtime_config_override(db: AsyncSession, key: str) -> None:
    """Remove one runtime configuration override."""
    existing = await db.get(SystemConfig, key)
    if existing is not None:
        await db.delete(existing)

    await db.flush()
    reset_runtime_config(key)


async def reset_all_runtime_config_overrides(db: AsyncSession) -> None:
    """Remove all runtime configuration overrides."""
    result = await db.execute(select(SystemConfig))
    for row in result.scalars().all():
        await db.delete(row)

    worker_env_result = await db.execute(select(WorkerEnvironmentVariable))
    for row in worker_env_result.scalars().all():
        await db.delete(row)

    await db.flush()
    reset_runtime_config()
