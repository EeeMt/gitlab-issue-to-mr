"""Helpers for persisted worker environment variables."""

from __future__ import annotations

import re
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_crypto import decrypt_config_secret, encrypt_config_secret
from app.models import WorkerEnvironmentVariable

WORKER_ENVIRONMENT_VARIABLE_KEY_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")

RESERVED_WORKER_ENVIRONMENT_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_SMALL_FAST_MODEL",
        "APPEND_SYSTEM_PROMPT",
        "BASE_BRANCH",
        "BRANCH_NAME",
        "CLAUDE_CODE_SUBAGENT_MODEL",
        "CLAUDE_MAX_TURNS",
        "CODIFY_COAUTHOR_EMAIL",
        "CODIFY_COAUTHOR_NAME",
        "CODIFY_CODEGRAPH_ENABLED",
        "CODIFY_CLI_BINARY_DIGEST",
        "CODIFY_ADAPTER_VERSION",
        "CODIFY_ATTEMPT_ID",
        "CODIFY_EVENT_SCHEMA",
        "CODIFY_GIT_CLONE_DEPTH",
        "CODIFY_GIT_CLONE_FILTER",
        "CODIFY_HARNESS_CLI_BIN",
        "CODIFY_HARNESS_CONTROL_TRANSPORT_KIND",
        "CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL",
        "CODIFY_HARNESS_KEY",
        "CODIFY_HARNESS_MODEL_PROTOCOLS",
        "CODIFY_HARNESS_SANDBOX_MODE",
        "CODIFY_MODEL_PROTOCOL",
        "CODIFY_RUNTIME_BUNDLE_DIGEST",
        "CODIFY_RUNTIME_CONTRACT_VERSION",
        "CODIFY_RUNTIME_DIR",
        "CODIFY_RUNTIME_EVENT_SCHEMA",
        "CODIFY_RUNTIME_MANIFEST_DIGEST",
        "CODIFY_ARTIFACT_DIR",
        "CODIFY_TASK_PROMPT_FILE",
        "CODIFY_TASK_SKILLS_DIR",
        "CODIFY_WORKER_PROFILE_ID",
        "CUSTOM_CA_BUNDLE",
        "GITLAB_TOKEN",
        "GITLAB_URL",
        "GIT_AUTHOR_EMAIL",
        "GIT_AUTHOR_NAME",
        "ISSUE_ID",
        "ISSUE_TITLE",
        "MR_IID",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENCODE_API_KEY",
        "OPENCODE_BASE_URL",
        "OPENCODE_MODEL",
        "PI_API_KEY",
        "PI_BASE_URL",
        "PI_MODEL",
        "PROJECT_ID",
        "REQUIRE_CHANGES",
        "RESUME_SESSION",
        "CODIFY_RESUME_SESSION",
        "START_FRESH_SESSION",
        "TARGET_BRANCH",
        "TASK_ID",
        "TASK_MODE",
        "TASK_TIMEOUT",
        "USER_PROMPT",
    }
)

# These namespaces carry frozen Provider, Bundle, Harness, and adapter state.
# Profile/shared custom environment is merged into the container environment,
# so admitting even a newly introduced key in one of these namespaces would
# let configuration redirect a frozen runner, CLI, transport, or credential.
# Keep the list namespace-based rather than an ever-growing enumeration of
# individual knobs.  Ordinary integration variables (for example CUSTOM_*)
# remain supported.
_FROZEN_RUNTIME_ENVIRONMENT_PREFIXES = (
    "ANTHROPIC_",
    "CLAUDE_",
    "CODEX_",
    "CODIFY_",
    "OPENAI_",
    "OPENCODE_",
    "PI_",
)


def validate_worker_environment_variable_key(key: str) -> str:
    """Validate a custom worker environment variable key."""
    if not WORKER_ENVIRONMENT_VARIABLE_KEY_PATTERN.fullmatch(key):
        raise ValueError("Worker environment variable keys must match ^[A-Z_][A-Z0-9_]*$")
    if key in RESERVED_WORKER_ENVIRONMENT_KEYS or key.startswith(
        _FROZEN_RUNTIME_ENVIRONMENT_PREFIXES
    ):
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


def serialize_worker_environment_variable_for_runtime(
    row: WorkerEnvironmentVariable,
) -> dict[str, Any]:
    """Serialize one worker environment variable for runtime config responses."""
    return {
        "id": row.id,
        "key": row.key,
        "value": "" if row.is_secret else row.value,
        "is_secret": row.is_secret,
        "value_configured": row.value is not None,
    }


async def list_worker_environment_variables(
    db: AsyncSession,
) -> list[WorkerEnvironmentVariable]:
    """Load all persisted worker environment variables."""
    result = await db.execute(
        select(WorkerEnvironmentVariable).order_by(WorkerEnvironmentVariable.key.asc())
    )
    return list(result.scalars().all())


def _item_field(item: Any, field: str) -> Any:
    """Read one field from a replacement item."""
    if isinstance(item, dict):
        return item[field]
    return getattr(item, field)


async def replace_worker_environment_variables(
    db: AsyncSession,
    items: Iterable[Any],
) -> list[WorkerEnvironmentVariable]:
    """Replace all persisted worker environment variables with the submitted list."""
    existing_rows = await list_worker_environment_variables(db)
    existing_by_key = {row.key: row for row in existing_rows}
    seen_keys: set[str] = set()

    for item in items:
        key = validate_worker_environment_variable_key(_item_field(item, "key"))
        if key in seen_keys:
            raise ValueError(f"Duplicate worker environment variable key: {key}")
        seen_keys.add(key)

        value = _item_field(item, "value")
        is_secret = bool(_item_field(item, "is_secret"))

        if is_secret and value == "":
            existing_row = existing_by_key.get(key)
            if existing_row is None or not existing_row.is_secret:
                raise ValueError(
                    f"New secret worker environment variable {key} cannot use a blank value"
                )
            stored_value = existing_row.value
        else:
            stored_value = serialize_worker_environment_variable_value(
                value,
                is_secret=is_secret,
            )

        row = existing_by_key.get(key)
        if row is None:
            row = WorkerEnvironmentVariable(
                key=key,
                value=stored_value,
                is_secret=is_secret,
            )
            db.add(row)
            existing_by_key[key] = row
        else:
            row.value = stored_value
            row.is_secret = is_secret

    for row in existing_rows:
        if row.key not in seen_keys:
            await db.delete(row)

    await db.flush()
    return await list_worker_environment_variables(db)


def build_worker_environment_map(
    rows: Iterable[WorkerEnvironmentVariable],
) -> dict[str, str]:
    """Build a runtime environment map from persisted rows."""
    return {
        row.key: deserialize_worker_environment_variable_value(row.value, is_secret=row.is_secret)
        for row in rows
    }
