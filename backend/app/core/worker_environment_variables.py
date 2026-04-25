"""Helpers for persisted worker environment variables."""

from __future__ import annotations

import re
from typing import Iterable, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_crypto import decrypt_config_secret, encrypt_config_secret
from app.models import WorkerEnvironmentVariable

WORKER_ENVIRONMENT_VARIABLE_KEY_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")

RESERVED_WORKER_ENVIRONMENT_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "APPEND_SYSTEM_PROMPT",
        "BASE_BRANCH",
        "BRANCH_NAME",
        "CLAUDE_MAX_TURNS",
        "CODIFY_COAUTHOR_EMAIL",
        "CODIFY_COAUTHOR_NAME",
        "CUSTOM_CA_BUNDLE",
        "GITLAB_TOKEN",
        "GITLAB_URL",
        "GIT_AUTHOR_EMAIL",
        "GIT_AUTHOR_NAME",
        "ISSUE_ID",
        "ISSUE_TITLE",
        "MR_IID",
        "PROJECT_ID",
        "RESUME_SESSION",
        "TARGET_BRANCH",
        "TASK_ID",
        "TASK_TIMEOUT",
        "USER_PROMPT",
    }
)


def validate_worker_environment_variable_key(key: str) -> str:
    """Validate a custom worker environment variable key."""
    if not WORKER_ENVIRONMENT_VARIABLE_KEY_PATTERN.fullmatch(key):
        raise ValueError("Worker environment variable keys must match ^[A-Z_][A-Z0-9_]*$")
    if key in RESERVED_WORKER_ENVIRONMENT_KEYS:
        raise ValueError(f"Worker environment variable key {key} is reserved")
    return key


def serialize_worker_environment_variable_value(value: str, *, is_secret: bool) -> str:
    """Serialize a worker environment variable value for storage."""
    if is_secret:
        return encrypt_config_secret(value)
    return value


def deserialize_worker_environment_variable_value(value: str, *, is_secret: bool) -> str:
    """Deserialize a persisted worker environment variable value."""
    if is_secret:
        return decrypt_config_secret(value)
    return value


def serialize_worker_environment_variable_for_api(
    row: WorkerEnvironmentVariable,
) -> dict[str, Any]:
    """Serialize one worker environment variable for API responses."""
    return {
        "id": row.id,
        "key": row.key,
        "value": None if row.is_secret else row.value,
        "is_secret": row.is_secret,
        "value_configured": row.value is not None,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def list_worker_environment_variables(
    db: AsyncSession,
) -> list[WorkerEnvironmentVariable]:
    """Load all persisted worker environment variables."""
    result = await db.execute(
        select(WorkerEnvironmentVariable).order_by(WorkerEnvironmentVariable.key.asc())
    )
    return list(result.scalars().all())


def build_worker_environment_map(
    rows: Iterable[WorkerEnvironmentVariable],
) -> dict[str, str]:
    """Build a runtime environment map from persisted rows."""
    return {
        row.key: deserialize_worker_environment_variable_value(row.value, is_secret=row.is_secret)
        for row in rows
    }
