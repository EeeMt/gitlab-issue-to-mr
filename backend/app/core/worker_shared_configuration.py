"""Worker shared configuration, effective-config resolution, and digest.

The system shared configuration (``worker_shared_configurations`` singleton plus
``worker_shared_environment_variables``) is the common operational baseline.
Worker Profiles keep host/image/capability fields and a *diff* over the shared
fields. This module resolves the two layers into one immutable effective
configuration, statically validates the combination, and computes the
versioned effective-configuration digest that Task snapshots freeze.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.worker_environment_variables import (
    validate_worker_environment_variable_key,
)
from app.core.worker_kit import (
    BAKED_IMAGE_MODE,
    WORKER_RUNTIME_MODES,
    WorkerKitValidationError,
    validate_worker_kit_config,
    validate_worker_kit_mounts,
)
from app.models import (
    WorkerSharedConfiguration,
    WorkerSharedEnvironmentVariable,
)

logger = logging.getLogger(__name__)

EFFECTIVE_CONFIG_SCHEMA = "codify.worker-effective-config/v1"

WORKER_KIT_SOURCE_SYSTEM = "system"
WORKER_KIT_SOURCE_PROFILE = "profile"
WORKER_KIT_SOURCES = frozenset({WORKER_KIT_SOURCE_SYSTEM, WORKER_KIT_SOURCE_PROFILE})

ENV_OPERATION_SET = "set"
ENV_OPERATION_MASK = "mask"
ENV_OPERATIONS = frozenset({ENV_OPERATION_SET, ENV_OPERATION_MASK})


@dataclass(frozen=True)
class WorkerSharedConfigurationContext:
    """The shared baseline loaded for one resolution, or an empty baseline."""

    row: WorkerSharedConfiguration | None = None
    environment_variables: tuple[WorkerSharedEnvironmentVariable, ...] = ()

    @property
    def revision(self) -> int | None:
        return self.row.revision if self.row is not None else None


@dataclass(frozen=True)
class EffectiveWorkerConfiguration:
    """Fully resolved worker configuration after shared + profile merge.

    ``environment_variables`` entries use the persisted form ``{key, value,
    is_secret}`` where a secret ``value`` is the stored ciphertext. The fields
    ``runtime_mode`` and ``worker_kit_version`` mirror the snapshot columns so
    runtime validation helpers (e.g. skills) can read them off the resolved
    configuration.
    """

    image: str
    runtime_mode: str
    worker_kit_version: str | None
    worker_kit_path: str | None
    volume_mounts: tuple[dict[str, str], ...]
    environment_variables: tuple[dict[str, Any], ...]
    pre_script: str
    post_script: str
    default_execute_run_instruction_template: str
    default_plan_run_instruction_template: str
    ci_auto_repair_run_instruction_template: str
    shared_configuration_revision: int | None = None


def profile_inherits_shared(profile: Any) -> bool:
    """Return whether a profile inherits anything from the shared baseline.

    A profile that is fully explicit (kit source ``profile``, every scalar set,
    no masks, no ``mask`` environment rows) resolves identically without the
    shared configuration, so callers can skip the shared read entirely.
    """
    if (
        getattr(profile, "worker_kit_source", WORKER_KIT_SOURCE_PROFILE)
        == WORKER_KIT_SOURCE_SYSTEM
    ):
        return True
    for field in (
        "pre_script",
        "post_script",
        "default_execute_run_instruction_template",
        "default_plan_run_instruction_template",
        "ci_auto_repair_run_instruction_template",
    ):
        if getattr(profile, field, None) is None:
            return True
    if getattr(profile, "volume_mount_masks", None):
        return True
    for row in getattr(profile, "environment_variables", None) or []:
        operation = str(_profile_value(row, "operation", ENV_OPERATION_SET) or "").strip()
        if operation == ENV_OPERATION_MASK:
            return True
    return False


async def load_shared_configuration(
    db: AsyncSession,
) -> WorkerSharedConfigurationContext:
    """Load the shared configuration singleton and its environment variables."""
    row = await db.get(WorkerSharedConfiguration, 1)
    if row is None:
        return WorkerSharedConfigurationContext()
    result = await db.execute(
        select(WorkerSharedEnvironmentVariable)
        .where(WorkerSharedEnvironmentVariable.worker_shared_configuration_id == row.id)
        .order_by(WorkerSharedEnvironmentVariable.key.asc())
    )
    return WorkerSharedConfigurationContext(
        row=row,
        environment_variables=tuple(result.scalars().all()),
    )


def _profile_value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _resolve_script(profile_value: Any, shared_value: str | None) -> str:
    # NULL inherits the shared script; "" is an explicit disable; non-empty is an
    # override. Without a shared baseline the inherited value is empty.
    if profile_value is None:
        return shared_value or ""
    return str(profile_value)


def _resolve_template(profile_value: Any, shared_value: str | None) -> str:
    # NULL inherits the shared template; non-empty is an override. Empty
    # templates are rejected by validation.
    if profile_value is None:
        return shared_value or ""
    return str(profile_value)


def _merge_mounts(profile: Any, shared_row: Any) -> tuple[dict[str, str], ...]:
    from app.core.worker_profiles import parse_worker_profile_mounts

    effective: dict[str, dict[str, str]] = {}
    shared_mounts = (
        parse_worker_profile_mounts(shared_row.volume_mounts)
        if shared_row is not None
        else []
    )
    for mount in shared_mounts:
        effective[mount["container_path"]] = mount
    for mask_path in _profile_value(profile, "volume_mount_masks", None) or []:
        normalized = str(mask_path).strip()
        if normalized:
            effective.pop(normalized, None)
    for mount in parse_worker_profile_mounts(
        _profile_value(profile, "volume_mounts", None)
    ):
        effective[mount["container_path"]] = mount
    return tuple(sorted(effective.values(), key=lambda m: m["container_path"]))


def _merge_environment(
    profile: Any,
    shared_env: Sequence[Any],
) -> tuple[dict[str, Any], ...]:
    effective: dict[str, dict[str, Any]] = {}
    for row in shared_env:
        key = str(_profile_value(row, "key") or "")
        if key:
            effective[key] = {
                "key": key,
                "value": _profile_value(row, "value", "") or "",
                "is_secret": bool(_profile_value(row, "is_secret", False)),
            }
    for row in _profile_value(profile, "environment_variables", None) or []:
        key = str(_profile_value(row, "key") or "")
        if not key:
            continue
        operation = str(_profile_value(row, "operation", ENV_OPERATION_SET) or "").strip()
        operation = operation or ENV_OPERATION_SET
        if operation == ENV_OPERATION_MASK:
            effective.pop(key, None)
        else:
            effective[key] = {
                "key": key,
                "value": _profile_value(row, "value", "") or "",
                "is_secret": bool(_profile_value(row, "is_secret", False)),
            }
    return tuple(sorted(effective.values(), key=lambda item: item["key"]))


def resolve_effective_configuration(
    profile: Any,
    shared: WorkerSharedConfigurationContext | None = None,
) -> EffectiveWorkerConfiguration:
    """Resolve the profile's full effective configuration.

    A missing shared context (``None``) is treated as an empty baseline: the
    profile's own explicit values are used as-is, which is exactly the behavior
    before shared configuration existed.
    """
    from app.core.worker_profiles import WorkerProfileValidationError

    shared_row = shared.row if shared is not None else None
    shared_env = shared.environment_variables if shared is not None else ()
    revision = shared.revision if shared is not None else None

    kit_source = (
        str(_profile_value(profile, "worker_kit_source", WORKER_KIT_SOURCE_PROFILE) or "")
        .strip()
        or WORKER_KIT_SOURCE_PROFILE
    )
    if kit_source not in WORKER_KIT_SOURCES:
        raise WorkerProfileValidationError(
            f"worker_kit_source must be one of: {', '.join(sorted(WORKER_KIT_SOURCES))}"
        )
    if kit_source == WORKER_KIT_SOURCE_SYSTEM:
        if shared_row is None:
            raise WorkerProfileValidationError(
                "worker_kit_source=system requires a configured shared worker "
                "configuration"
            )
        raw_runtime_mode = shared_row.runtime_mode or BAKED_IMAGE_MODE
        raw_kit_version = shared_row.worker_kit_version
        raw_kit_path = shared_row.worker_kit_path
    else:
        raw_runtime_mode = _profile_value(profile, "runtime_mode", BAKED_IMAGE_MODE)
        raw_kit_version = _profile_value(profile, "worker_kit_version", None)
        raw_kit_path = _profile_value(profile, "worker_kit_path", None)
    try:
        runtime_mode, kit_version, kit_path = validate_worker_kit_config(
            runtime_mode=raw_runtime_mode,
            worker_kit_version=raw_kit_version,
            worker_kit_path=raw_kit_path,
        )
    except WorkerKitValidationError as exc:
        raise WorkerProfileValidationError(str(exc)) from exc

    pre_script = _resolve_script(
        _profile_value(profile, "pre_script", ""),
        shared_row.pre_script if shared_row is not None else None,
    )
    post_script = _resolve_script(
        _profile_value(profile, "post_script", ""),
        shared_row.post_script if shared_row is not None else None,
    )
    execute_template = _resolve_template(
        _profile_value(profile, "default_execute_run_instruction_template", ""),
        shared_row.default_execute_run_instruction_template
        if shared_row is not None
        else None,
    )
    plan_template = _resolve_template(
        _profile_value(profile, "default_plan_run_instruction_template", ""),
        shared_row.default_plan_run_instruction_template
        if shared_row is not None
        else None,
    )
    ci_template = _resolve_template(
        _profile_value(profile, "ci_auto_repair_run_instruction_template", ""),
        shared_row.ci_auto_repair_run_instruction_template
        if shared_row is not None
        else None,
    )

    return EffectiveWorkerConfiguration(
        image=str(_profile_value(profile, "image", "")),
        runtime_mode=runtime_mode,
        worker_kit_version=kit_version,
        worker_kit_path=kit_path,
        volume_mounts=_merge_mounts(profile, shared_row),
        environment_variables=_merge_environment(profile, shared_env),
        pre_script=pre_script,
        post_script=post_script,
        default_execute_run_instruction_template=execute_template,
        default_plan_run_instruction_template=plan_template,
        ci_auto_repair_run_instruction_template=ci_template,
        shared_configuration_revision=revision,
    )


def validate_effective_configuration(
    effective: EffectiveWorkerConfiguration,
) -> None:
    """Run static combination validation over a fully resolved configuration."""
    from app.core.worker_profiles import (
        WorkerProfileValidationError,
        validate_profile_templates,
        validate_worker_profile_mounts,
    )

    if effective.runtime_mode not in WORKER_RUNTIME_MODES:
        raise WorkerProfileValidationError(
            f"runtime_mode must be one of: {', '.join(sorted(WORKER_RUNTIME_MODES))}"
        )
    try:
        merged_mounts = validate_worker_profile_mounts(list(effective.volume_mounts))
        validate_worker_kit_mounts(effective.runtime_mode, merged_mounts)
    except WorkerKitValidationError as exc:
        raise WorkerProfileValidationError(str(exc)) from exc
    for item in effective.environment_variables:
        key = str(item.get("key") or "")
        try:
            validate_worker_environment_variable_key(key)
        except ValueError as exc:
            raise WorkerProfileValidationError(str(exc)) from exc
    validate_profile_templates(
        execute_template=effective.default_execute_run_instruction_template,
        plan_template=effective.default_plan_run_instruction_template,
        ci_template=effective.ci_auto_repair_run_instruction_template,
    )


def compute_effective_configuration_digest(
    *,
    image: str,
    runtime_mode: str,
    worker_kit_version: str | None,
    worker_kit_path: str | None,
    volume_mounts: Sequence[Mapping[str, Any]],
    environment_variables: Sequence[Mapping[str, Any]],
    pre_script: str,
    post_script: str,
    default_execute_run_instruction_template: str,
    default_plan_run_instruction_template: str,
    ci_auto_repair_run_instruction_template: str,
) -> str:
    """Compute the SHA-256 of the versioned, normalized effective config.

    Secret environment variable values are replaced with the digest of their
    stored ciphertext so the digest is stable across reads yet never embeds
    plaintext (design §10.1).
    """
    mounts = [
        {
            "host_path": str(mount.get("host_path") or ""),
            "container_path": str(mount.get("container_path") or ""),
            "mode": str(mount.get("mode") or "ro"),
        }
        for mount in volume_mounts
    ]
    mounts.sort(key=lambda mount: (mount["container_path"], mount["host_path"]))
    environment: list[dict[str, Any]] = []
    for item in environment_variables:
        key = str(item.get("key") or "")
        is_secret = bool(item.get("is_secret"))
        value = str(item.get("value") or "")
        if is_secret:
            value = hashlib.sha256(value.encode("utf-8")).hexdigest()
        environment.append({"key": key, "value": value, "is_secret": is_secret})
    environment.sort(key=lambda entry: entry["key"])
    payload = {
        "schema": EFFECTIVE_CONFIG_SCHEMA,
        "image": image,
        "runtime_mode": runtime_mode,
        "worker_kit_version": worker_kit_version,
        "worker_kit_path": worker_kit_path,
        "mounts": mounts,
        "environment": environment,
        "pre_script": pre_script,
        "post_script": post_script,
        "run_instruction_templates": {
            "execute": default_execute_run_instruction_template,
            "plan": default_plan_run_instruction_template,
            "ci_auto_repair": ci_auto_repair_run_instruction_template,
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def effective_configuration_digest(
    effective: EffectiveWorkerConfiguration,
) -> str:
    """Convenience digest for an already resolved effective configuration."""
    return compute_effective_configuration_digest(
        image=effective.image,
        runtime_mode=effective.runtime_mode,
        worker_kit_version=effective.worker_kit_version,
        worker_kit_path=effective.worker_kit_path,
        volume_mounts=effective.volume_mounts,
        environment_variables=effective.environment_variables,
        pre_script=effective.pre_script,
        post_script=effective.post_script,
        default_execute_run_instruction_template=(
            effective.default_execute_run_instruction_template
        ),
        default_plan_run_instruction_template=effective.default_plan_run_instruction_template,
        ci_auto_repair_run_instruction_template=(
            effective.ci_auto_repair_run_instruction_template
        ),
    )
