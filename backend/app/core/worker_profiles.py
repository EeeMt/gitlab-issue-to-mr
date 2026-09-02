"""Worker profile validation, default resolution, and task snapshots."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_effective_settings
from app.core.config_crypto import decrypt_config_secret
from app.core.docker_client import (
    DockerClientWrapper,
    DockerConnectionConfig,
    canonicalize_docker_host,
    resolve_docker_connection,
)
from app.core.harness_options import (
    deep_merge_options,
    validate_namespaced_options,
    validate_task_overrides,
)
from app.core.harness_protocol import HARNESS_CONTRACT_VERSION, HARNESS_CONTRACT_VERSION_V2
from app.core.harness_registry import capability_policy
from app.core.skills import (
    SkillValidationError,
    hydrate_skill_snapshots,
    skill_snapshots_from_task_snapshot,
    validate_runtime_supports_skills,
)
from app.core.task_prompt import (
    FREEFORM_RUN_INSTRUCTION_TEMPLATE,
    TaskPromptValidationError,
    validate_run_instruction_template,
)
from app.core.worker_docker_targets import docker_daemon_key
from app.core.worker_environment_variables import (
    serialize_worker_environment_variable_value,
    validate_worker_environment_variable_key,
)
from app.core.worker_kit import (
    BAKED_IMAGE_MODE,
    KIT_CONTAINER_PATH,
    KIT_CONTAINER_USER,
    KIT_ENTRYPOINT,
    MOUNTED_KIT_MODE,
    WorkerKitValidationError,
    validate_no_worker_kit_mount_collision,
    validate_worker_kit_config,
    validate_worker_kit_mounts,
    worker_kit_environment,
    worker_kit_mounts,
)
from app.core.worker_kit_inventory import validate_worker_kit_identity
from app.core.worker_runtime_readiness import (
    fingerprint_from_docker_target,
    runtime_verification_input_digest,
)
from app.core.worker_shared_configuration import (
    load_shared_configuration,
    resolve_effective_configuration,
    snapshot_effective_configuration_digest,
    validate_effective_configuration,
)
from app.models import (
    AIProvider,
    Issue,
    Task,
    TaskSkillVersionReference,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
    WorkerProfileEnvironmentVariable,
)

logger = logging.getLogger(__name__)

_LEGACY_IGNORED_RUNTIME_ENVIRONMENT_KEYS = frozenset(
    {"CODIFY_RUNTIME_DIR", "CODIFY_ARTIFACT_DIR"}
)
_V2_IMAGE_IDENTITY_KEY = "v2_worker_image_identity"
_V2_HARNESS_EVIDENCE_KEY = "v2_harness_verification_evidence"
_V2_KIT_IDENTITY_KEY = "worker_kit_identity"
_V2_IMAGE_IDENTITY_SCHEMA = "codify.worker-image-identity/v1"
_V2_HARNESS_EVIDENCE_SCHEMA = "codify.worker-harness-verification/v1"
_LINUX_PLATFORM_RE = re.compile(r"^linux/[A-Za-z0-9][A-Za-z0-9_.-]*$")
_IMAGE_REFERENCE_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_V2_CLI_SOURCES = frozenset({"worker_kit", "host_mount"})


def _linux_platform(value: object) -> bool:
    return isinstance(value, str) and _LINUX_PLATFORM_RE.fullmatch(value) is not None


def validate_v2_worker_image_identity(identity: object) -> dict[str, str]:
    """Validate the non-secret image identity frozen for an explicit V2 Task."""
    if not isinstance(identity, Mapping) or identity.get("schema") != _V2_IMAGE_IDENTITY_SCHEMA:
        raise WorkerProfileValidationError("explicit V2 Profile has no verified Worker image identity")
    required = ("daemon_key", "image_reference", "image_id", "runtime_platform")
    normalized = {key: identity.get(key) for key in required}
    if not all(isinstance(value, str) and value for value in normalized.values()):
        raise WorkerProfileValidationError("explicit V2 Profile has an incomplete Worker image identity")
    if any(character.isspace() for character in normalized["daemon_key"]):
        raise WorkerProfileValidationError("explicit V2 Worker image identity has an invalid daemon key")
    if _IMAGE_REFERENCE_RE.fullmatch(normalized["image_reference"]) is None:
        raise WorkerProfileValidationError("explicit V2 Worker image identity is not repository-digest pinned")
    if _IMAGE_ID_RE.fullmatch(normalized["image_id"]) is None:
        raise WorkerProfileValidationError("explicit V2 Worker image identity has an invalid image ID")
    if not _linux_platform(normalized["runtime_platform"]):
        raise WorkerProfileValidationError("explicit V2 Worker image identity has an invalid platform")
    return {"schema": _V2_IMAGE_IDENTITY_SCHEMA, **normalized}


def _repository_name(image: str) -> str:
    reference = image.split("@", 1)[0]
    last_slash = reference.rfind("/")
    last_colon = reference.rfind(":")
    return reference[:last_colon] if last_colon > last_slash else reference


def validate_v2_worker_kit_identity(identity: object) -> dict[str, str]:
    """Validate the frozen content-addressed Worker Kit identity fail-closed."""
    try:
        return validate_worker_kit_identity(identity)
    except ValueError as exc:
        raise WorkerProfileValidationError(
            f"explicit V2 Profile has no verified Worker Kit identity: {exc}"
        ) from exc


def validate_v2_cli_identity(identity: object, *, harness_key: str) -> dict[str, str]:
    """Validate the selected V2 Harness CLI identity frozen by verification."""
    if not isinstance(identity, Mapping):
        raise WorkerProfileValidationError(
            f"explicit V2 Profile has no verified CLI identity for Harness {harness_key!r}"
        )
    required = ("source", "executable_path", "version", "binary_digest")
    normalized = {key: identity.get(key) for key in required}
    if not all(isinstance(value, str) and value for value in normalized.values()):
        raise WorkerProfileValidationError(
            f"explicit V2 Profile has an incomplete CLI identity for Harness {harness_key!r}"
        )
    if normalized["source"] not in _V2_CLI_SOURCES:
        raise WorkerProfileValidationError(
            f"explicit V2 Profile has an invalid CLI source for Harness {harness_key!r}"
        )
    executable_path = normalized["executable_path"]
    if (
        not executable_path.startswith("/")
        or "\\" in executable_path
        or str(PurePosixPath(executable_path)) != executable_path
    ):
        raise WorkerProfileValidationError(
            f"explicit V2 Profile has an unsafe CLI path for Harness {harness_key!r}"
        )
    if normalized["source"] == "worker_kit" and not executable_path.startswith(
        f"{KIT_CONTAINER_PATH}/"
    ):
        raise WorkerProfileValidationError(
            f"explicit V2 Worker Kit CLI for Harness {harness_key!r} is outside the Kit"
        )
    if _SHA256_RE.fullmatch(normalized["binary_digest"]) is None:
        raise WorkerProfileValidationError(
            f"explicit V2 Profile has an invalid CLI digest for Harness {harness_key!r}"
        )
    return normalized


def current_runtime_verification_digest(
    profile: Any, effective: Any, settings: Any, *, harness_key: str | None = None
) -> str:
    """Recompute the exact non-secret verification input authority for a snapshot."""
    connection = resolve_docker_connection(
        settings,
        docker_host=getattr(profile, "docker_host", None),
        docker_tls_ca=getattr(profile, "docker_tls_ca", None),
        docker_tls_cert=getattr(profile, "docker_tls_cert", None),
        docker_tls_key=getattr(profile, "docker_tls_key", None),
    )
    return runtime_verification_input_digest(
        docker_daemon_key=docker_daemon_key(connection), image=effective.image,
        runtime_mode=effective.runtime_mode, worker_kit_version=effective.worker_kit_version,
        worker_kit_path=effective.worker_kit_path, volume_mounts=list(effective.volume_mounts),
        environment_variables=[{"key": str(item.get("key") or ""), "value": str(item.get("value") or "")}
            for item in effective.environment_variables if not bool(item.get("is_secret"))],
        harness_key=harness_key or getattr(profile, "default_harness_key", None) or "claude",
        enabled_harnesses=list(getattr(profile, "enabled_harnesses", None) or ["claude"]),
        harness_constraints=dict(getattr(profile, "harness_constraints", None) or {}),
        harness_runtimes=dict(getattr(profile, "harness_runtimes", None) or {}),
        require_skill_support=effective.runtime_mode == MOUNTED_KIT_MODE,
    )


def eligible_v2_harness_keys(profile: Any) -> tuple[str, ...]:
    """Return enabled harnesses that explicitly opt into the V2 contract."""
    runtimes = getattr(profile, "harness_runtimes", None) or {}
    enabled = getattr(profile, "enabled_harnesses", None) or ["claude"]
    return tuple(
        key for key in dict.fromkeys(enabled)
        if isinstance(key, str)
        and isinstance(runtimes, Mapping)
        and isinstance(runtimes.get(key), Mapping)
        and runtimes[key].get("contract_version") == HARNESS_CONTRACT_VERSION_V2
    )


def validate_v2_harness_evidence(
    evidence: object,
    *,
    harness_key: str,
    verification_digest: str,
    image_identity: Mapping[str, str],
    generation: int,
) -> dict[str, Any]:
    """Validate one frozen per-Harness V2 verification record fail-closed."""
    if not isinstance(evidence, Mapping) or evidence.get("schema") != _V2_HARNESS_EVIDENCE_SCHEMA:
        raise WorkerProfileValidationError(f"explicit V2 Profile has no verified evidence for Harness {harness_key!r}")
    if evidence.get("harness_key") != harness_key:
        raise WorkerProfileValidationError("explicit V2 Profile verification evidence has the wrong Harness key")
    if evidence.get("contract_version") != HARNESS_CONTRACT_VERSION_V2:
        raise WorkerProfileValidationError("explicit V2 Profile verification evidence has the wrong contract")
    if evidence.get("verification_input_digest") != verification_digest:
        raise WorkerProfileValidationError("explicit V2 Profile verification evidence is stale")
    if evidence.get("generation") != generation:
        raise WorkerProfileValidationError("explicit V2 Profile verification evidence generation is stale")
    if evidence.get("image_identity") != dict(image_identity):
        raise WorkerProfileValidationError("explicit V2 Profile verification evidence image identity is stale")
    adapter = evidence.get("adapter")
    if (
        not isinstance(adapter, Mapping)
        or not isinstance(adapter.get("version"), str)
        or not adapter["version"]
        or not isinstance(adapter.get("digest"), str)
        or _SHA256_RE.fullmatch(adapter["digest"]) is None
    ):
        raise WorkerProfileValidationError("explicit V2 Profile verification evidence has an invalid Adapter identity")
    if not isinstance(evidence.get("verified_at"), str) or not evidence["verified_at"]:
        raise WorkerProfileValidationError("explicit V2 Profile verification evidence has no verification time")
    cli = validate_v2_cli_identity(evidence.get("cli"), harness_key=harness_key)
    normalized = dict(evidence)
    normalized["cli"] = cli
    return normalized


def inspect_v2_worker_image_identity(connection: DockerConnectionConfig, image: str) -> dict[str, str]:
    """Read the selected daemon image's immutable identity fail-closed.

    The record covers the repository digest, image ID and platform of the
    exact daemon image — no image-owned CLI lock exists any more (Worker Kit
    owns the Harness CLIs). The returned record contains no Docker URL or
    credentials.
    """
    client = DockerClientWrapper(connection)
    try:
        image_obj = client.client.images.get(image)
        attrs = image_obj.attrs or {}
        repo_digests = [str(item) for item in (attrs.get("RepoDigests") or []) if "@sha256:" in str(item)]
        expected_repo = _repository_name(image)
        candidates = [item for item in repo_digests if _repository_name(item) == expected_repo]
        if len(candidates) != 1:
            raise WorkerProfileValidationError(
                "explicit V2 Worker image must have exactly one repository digest matching its configured image"
            )
        image_reference = candidates[0]
        image_id = attrs.get("Id")
        platform = f"{attrs.get('Os')}/{attrs.get('Architecture')}"
        if not isinstance(image_id, str) or not image_id or not _linux_platform(platform):
            raise WorkerProfileValidationError("explicit V2 Worker image has no immutable ID or linux platform")
        identity = {
            "schema": _V2_IMAGE_IDENTITY_SCHEMA,
            "daemon_key": docker_daemon_key(connection),
            "image_reference": image_reference,
            "image_id": image_id,
            "runtime_platform": platform,
        }
        return validate_v2_worker_image_identity(identity)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001 - preserve inspection error
            pass


class WorkerProfileValidationError(ValueError):
    """Raised when a worker profile payload is invalid."""


_SYSTEM_MOUNT_ROOTS = (
    PurePosixPath("/workspace"),
    PurePosixPath("/home/codify/.claude"),
    PurePosixPath("/opt/codify-issue-shared"),
    PurePosixPath("/opt/codify-issue-meta"),
    PurePosixPath("/tmp/codify-runtime"),
)
_SEALED_SYSTEM_MOUNT_ROOTS = {
    PurePosixPath("/opt/codify-issue-meta"),
    PurePosixPath("/tmp/codify-runtime"),
}


@dataclass(frozen=True)
class TaskWorkerRuntime:
    """Resolved task worker runtime loaded from a task snapshot."""

    image: str
    codegraph_enabled: bool
    volume_mounts: list[dict[str, str]]
    environment: dict[str, str]
    pre_script: str
    post_script: str
    skills: list[dict[str, Any]] = field(default_factory=list)
    runtime_mode: str = BAKED_IMAGE_MODE
    worker_kit_version: str | None = None
    worker_kit_path: str | None = None
    docker_host: str | None = None
    docker_tls_ca: str | None = None
    docker_tls_cert: str | None = None
    docker_tls_key: str | None = None

    def docker_connection(self, settings: Any) -> DockerConnectionConfig:
        return resolve_docker_connection(
            settings,
            docker_host=self.docker_host,
            docker_tls_ca=self.docker_tls_ca,
            docker_tls_cert=self.docker_tls_cert,
            docker_tls_key=self.docker_tls_key,
        )

    def container_overrides(self) -> dict[str, Any]:
        """Return Docker arguments and environment owned by the delivery mode."""
        try:
            mode, kit_version, kit_path = validate_worker_kit_config(
                runtime_mode=self.runtime_mode,
                worker_kit_version=self.worker_kit_version,
                worker_kit_path=self.worker_kit_path,
            )
        except WorkerKitValidationError as exc:
            raise WorkerProfileValidationError(str(exc)) from exc
        if mode != MOUNTED_KIT_MODE:
            return {"volumes": {}, "environment": {}, "entrypoint": None, "user": None}
        assert kit_version is not None and kit_path is not None
        try:
            validate_no_worker_kit_mount_collision(self.volume_mounts)
        except WorkerKitValidationError as exc:
            raise WorkerProfileValidationError(str(exc)) from exc
        return {
            "volumes": worker_kit_mounts(kit_path),
            "environment": worker_kit_environment(kit_version),
            "entrypoint": KIT_ENTRYPOINT,
            "user": KIT_CONTAINER_USER,
        }


def _profile_value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _validate_environment_key(key: str) -> str:
    if len(key) > 255:
        raise WorkerProfileValidationError(
            "Worker environment variable keys must be 255 characters or fewer"
        )
    try:
        return validate_worker_environment_variable_key(key)
    except ValueError as exc:
        raise WorkerProfileValidationError(str(exc)) from exc


def validate_worker_profile_docker_target(
    *,
    docker_host: str | None,
    docker_tls_ca: str | None,
    docker_tls_cert: str | None,
    docker_tls_key: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Normalize and validate one optional profile-scoped Docker target."""
    host = (docker_host or "").strip() or None
    tls_values = tuple(
        (value or "").strip() or None
        for value in (docker_tls_ca, docker_tls_cert, docker_tls_key)
    )
    if host is None:
        if any(tls_values):
            raise WorkerProfileValidationError(
                "Docker TLS paths require a profile Docker host"
            )
        return None, None, None, None

    parsed = urlparse(host)
    if parsed.scheme not in {"unix", "tcp", "https"}:
        raise WorkerProfileValidationError(
            "docker_host must use unix, tcp, or https"
        )

    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WorkerProfileValidationError(
            "docker_host must not contain credentials, query parameters, or fragments"
        )
    if parsed.scheme in {"tcp", "https"}:
        try:
            parsed.port
        except ValueError as exc:
            raise WorkerProfileValidationError("docker_host has an invalid port") from exc
        if parsed.hostname is None:
            raise WorkerProfileValidationError("docker_host must include a hostname")
        if parsed.path not in {"", "/"}:
            raise WorkerProfileValidationError("docker_host must not include a URL path")
    elif not parsed.path or not os.path.isabs(parsed.path):
        raise WorkerProfileValidationError(
            "unix docker_host must include an absolute socket path"
        )

    configured_tls_paths = sum(value is not None for value in tls_values)
    if configured_tls_paths not in {0, 3}:
        raise WorkerProfileValidationError(
            "Docker TLS CA, certificate, and key paths must be configured together"
        )
    if configured_tls_paths and parsed.scheme == "unix":
        raise WorkerProfileValidationError(
            f"Docker TLS file paths are not supported for {parsed.scheme} endpoints"
        )
    for path in tls_values:
        if path is not None and not os.path.isabs(path):
            raise WorkerProfileValidationError("Docker TLS paths must be absolute")
    try:
        canonicalize_docker_host(host, tls_enabled=configured_tls_paths == 3)
    except Exception as exc:
        raise WorkerProfileValidationError(f"Invalid docker_host: {exc}") from exc
    return host, tls_values[0], tls_values[1], tls_values[2]


def validate_worker_profile_mounts(raw_mounts: Any) -> list[dict[str, str]]:
    """Validate and normalize worker profile mount entries."""
    if raw_mounts in (None, ""):
        return []
    if not isinstance(raw_mounts, list):
        raise WorkerProfileValidationError("volume_mounts must be a list")

    normalized: list[dict[str, str]] = []
    seen_host_paths: set[str] = set()
    seen_container_paths: set[str] = set()
    for mount in raw_mounts:
        if not isinstance(mount, Mapping):
            raise WorkerProfileValidationError("volume mount entries must be objects")
        host_path = str(mount.get("host_path") or "").strip()
        container_path = str(mount.get("container_path") or "").strip()
        mode = str(mount.get("mode") or "ro").strip().lower()
        if not host_path or not container_path:
            raise WorkerProfileValidationError(
                "volume mounts require host_path and container_path"
            )
        if not os.path.isabs(host_path):
            raise WorkerProfileValidationError("volume mount host_path must be absolute")
        if not os.path.isabs(container_path):
            raise WorkerProfileValidationError(
                "volume mount container_path must be absolute"
            )
        host_path = os.path.normpath(host_path)
        container_path = os.path.normpath(container_path)
        destination = PurePosixPath(container_path)
        for system_root in _SYSTEM_MOUNT_ROOTS:
            hides_system_root = destination == system_root or destination in system_root.parents
            enters_sealed_root = (
                system_root in _SEALED_SYSTEM_MOUNT_ROOTS
                and system_root in destination.parents
            )
            if hides_system_root or enters_sealed_root:
                raise WorkerProfileValidationError(
                    f"custom mount path {container_path} conflicts with Codify system path "
                    f"{system_root}"
                )
        if mode not in {"ro", "rw"}:
            raise WorkerProfileValidationError("volume mount mode must be ro or rw")
        if host_path in seen_host_paths:
            raise WorkerProfileValidationError(
                f"duplicate host mount path: {host_path}"
            )
        if container_path in seen_container_paths:
            raise WorkerProfileValidationError(
                f"duplicate container mount path: {container_path}"
            )
        seen_host_paths.add(host_path)
        seen_container_paths.add(container_path)
        normalized.append(
            {"host_path": host_path, "container_path": container_path, "mode": mode}
        )
    return normalized


def parse_worker_profile_mounts(value: Any) -> list[dict[str, str]]:
    """Parse legacy JSON string or JSON list profile mounts."""
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkerProfileValidationError("volume_mounts must be valid JSON") from exc
    return validate_worker_profile_mounts(value)


def validate_worker_profile_mount_masks(
    raw_masks: Any,
    *,
    volume_mounts: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Validate and normalize profile container-path masks.

    A mask names a shared container path this profile hides. Masks are stored
    normalized, must be absolute, must not repeat, and must not collide with a
    ``set`` override for the same container path (design §7.3).
    """
    if raw_masks in (None, ""):
        return []
    if not isinstance(raw_masks, list):
        raise WorkerProfileValidationError("volume_mount_masks must be a list")
    set_container_paths = {
        str(mount.get("container_path") or "").strip()
        for mount in volume_mounts
        if str(mount.get("container_path") or "").strip()
    }
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in raw_masks:
        container_path = str(raw_path or "").strip()
        if not container_path:
            raise WorkerProfileValidationError(
                "volume mount masks require a container_path"
            )
        if not os.path.isabs(container_path):
            raise WorkerProfileValidationError(
                "volume mount mask container_path must be absolute"
            )
        container_path = os.path.normpath(container_path)
        if container_path in seen:
            raise WorkerProfileValidationError(
                f"duplicate volume mount mask path: {container_path}"
            )
        if container_path in set_container_paths:
            raise WorkerProfileValidationError(
                f"volume mount path {container_path} cannot be both set and masked"
            )
        seen.add(container_path)
        normalized.append(container_path)
    return normalized


def validate_profile_templates(
    *,
    execute_template: str,
    plan_template: str,
    ci_template: str,
) -> tuple[str, str, str]:
    """Validate and normalize the three worker run-instruction templates."""
    try:
        return (
            validate_run_instruction_template(execute_template),
            validate_run_instruction_template(plan_template),
            validate_run_instruction_template(ci_template),
        )
    except TaskPromptValidationError as exc:
        raise WorkerProfileValidationError(str(exc)) from exc


def serialize_profile_environment_variable_for_api(
    row: WorkerProfileEnvironmentVariable,
) -> dict[str, Any]:
    """Serialize one profile env var without leaking secret values."""
    return {
        "id": row.id,
        "key": row.key,
        "value": None if row.is_secret else row.value,
        "is_secret": row.is_secret,
        "operation": getattr(row, "operation", "set") or "set",
        "value_configured": row.value is not None,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_worker_profile_for_api(
    profile: WorkerProfile,
    *,
    include_docker_target: bool = False,
) -> dict[str, Any]:
    """Serialize one worker profile for API responses."""
    payload = {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "enabled": profile.enabled,
        "is_default": profile.is_default,
        "image": profile.image,
        "worker_kit_source": getattr(profile, "worker_kit_source", "profile") or "profile",
        "runtime_mode": getattr(profile, "runtime_mode", BAKED_IMAGE_MODE),
        "worker_kit_version": getattr(profile, "worker_kit_version", None),
        "worker_kit_path": getattr(profile, "worker_kit_path", None),
        "codegraph_enabled": bool(getattr(profile, "codegraph_enabled", False)),
        "volume_mounts": profile.volume_mounts or [],
        "volume_mount_masks": getattr(profile, "volume_mount_masks", None) or [],
        "environment_variables": [
            serialize_profile_environment_variable_for_api(row)
            for row in profile.environment_variables
        ],
        "default_skill_ids": [
            skill.id for skill in (getattr(profile, "default_skills", None) or [])
        ],
        "pre_script": profile.pre_script,
        "post_script": profile.post_script,
        "default_execute_run_instruction_template": (
            profile.default_execute_run_instruction_template
        ),
        "default_plan_run_instruction_template": profile.default_plan_run_instruction_template,
        "ci_auto_repair_run_instruction_template": (
            profile.ci_auto_repair_run_instruction_template
        ),
        "verified_runtime_configuration_digest": getattr(
            profile, "verified_runtime_configuration_digest", None
        ),
        "enabled_harnesses": getattr(profile, "enabled_harnesses", None) or ["claude"],
        "default_harness_key": getattr(profile, "default_harness_key", None) or "claude",
        "harness_constraints": getattr(profile, "harness_constraints", None) or {},
        "harness_options": getattr(profile, "harness_options", None) or {},
        "image_digest": getattr(profile, "image_digest", None),
        "verified_at": getattr(profile, "verified_at", None),
        "harness_runtimes": getattr(profile, "harness_runtimes", None) or {},
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }
    if include_docker_target:
        payload.update(
            {
                "docker_host": getattr(profile, "docker_host", None),
                "docker_tls_ca": getattr(profile, "docker_tls_ca", None),
                "docker_tls_cert": getattr(profile, "docker_tls_cert", None),
                "docker_tls_key": getattr(profile, "docker_tls_key", None),
            }
        )
    return payload


def build_worker_profile_environment_map(
    rows: Iterable[Any],
    *,
    include_secrets: bool = True,
) -> dict[str, str]:
    """Build runtime env from snapshot environment rows."""
    env: dict[str, str] = {}
    for row in rows:
        raw_key = str(_profile_value(row, "key"))
        if raw_key in _LEGACY_IGNORED_RUNTIME_ENVIRONMENT_KEYS:
            logger.warning("Ignoring legacy reserved worker environment variable %s", raw_key)
            continue
        key = _validate_environment_key(raw_key)
        value = str(_profile_value(row, "value") or "")
        is_secret = bool(_profile_value(row, "is_secret"))
        if is_secret and not include_secrets:
            continue
        if not is_secret:
            env[key] = value
            continue
        try:
            env[key] = decrypt_config_secret(value)
        except Exception as exc:
            raise WorkerProfileValidationError(
                f"Unable to decrypt worker environment variable {key}"
            ) from exc
    return env


def build_worker_profile_volume_map(
    mounts: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    """Convert validated profile mounts to the Docker SDK volume mapping."""
    volumes: dict[str, dict[str, str]] = {}
    for mount in mounts:
        host_path = str(mount.get("host_path") or "")
        container_path = str(mount.get("container_path") or "")
        if host_path and container_path:
            volumes[host_path] = {
                "bind": container_path,
                "mode": str(mount.get("mode") or "ro"),
            }
    return volumes


async def list_worker_profiles(db: AsyncSession) -> list[WorkerProfile]:
    """Load all worker profiles for management screens."""
    result = await db.execute(
        select(WorkerProfile)
        .options(
            selectinload(WorkerProfile.environment_variables),
            selectinload(WorkerProfile.default_skills),
        )
        .order_by(WorkerProfile.is_default.desc(), WorkerProfile.name.asc())
    )
    return list(result.scalars().all())


async def get_default_worker_profile(db: AsyncSession) -> WorkerProfile | None:
    result = await db.execute(
        select(WorkerProfile)
        .where(WorkerProfile.is_default == True, WorkerProfile.enabled == True)
        .options(
            selectinload(WorkerProfile.environment_variables),
            selectinload(WorkerProfile.default_skills),
        )
        .execution_options(populate_existing=True)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_default_provider(db: AsyncSession) -> AIProvider | None:
    result = await db.execute(
        select(AIProvider)
        .where(AIProvider.is_default == True, AIProvider.is_disabled == False)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def resolve_worker_profile_for_issue(
    db: AsyncSession,
    issue: Issue,
    explicit_worker_profile_id: int | None = None,
    *,
    allow_system_default: bool = True,
) -> WorkerProfile:
    """Resolve the worker pinned to an Issue.

    ``explicit_worker_profile_id`` remains as a compatibility guard for internal callers. It
    may only repeat the Issue assignment; tasks cannot override the selected worker.
    """
    del allow_system_default
    candidate_id = getattr(issue, "worker_profile_id", None)
    if explicit_worker_profile_id is not None and explicit_worker_profile_id != candidate_id:
        raise WorkerProfileValidationError("Tasks must use the worker assigned to their issue")
    profile: WorkerProfile | None = None
    if candidate_id is not None:
        result = await db.execute(
            select(WorkerProfile)
            .where(WorkerProfile.id == candidate_id)
            .options(
                selectinload(WorkerProfile.environment_variables),
                selectinload(WorkerProfile.default_skills),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        profile = result.scalar_one_or_none()

    if profile is None:
        raise WorkerProfileValidationError("No worker is assigned to this issue")
    if not profile.enabled:
        raise WorkerProfileValidationError(f"Worker profile '{profile.name}' is disabled")
    return profile


async def resolve_provider_for_issue(
    db: AsyncSession,
    issue: Issue,
    explicit_provider_id: int | None = None,
    *,
    allow_system_default: bool = True,
) -> AIProvider:
    """Resolve explicit, issue default, then system default provider."""
    candidate_id = (
        explicit_provider_id
        if explicit_provider_id is not None
        else getattr(issue, "default_provider_id", None)
    )
    if candidate_id is not None:
        provider = await db.get(AIProvider, candidate_id)
        if provider is None:
            raise WorkerProfileValidationError(
                f"configured AI provider {candidate_id} not found"
            )
    elif allow_system_default:
        provider = await get_default_provider(db)
    else:
        provider = None
    if provider is None:
        raise WorkerProfileValidationError("No enabled AI provider is configured for this issue")
    if provider.is_disabled:
        raise WorkerProfileValidationError(f"AI provider '{provider.name}' is disabled")
    return provider


def _freeze_harness_options(
    profile: WorkerProfile,
    task_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and deep-merge the Profile's namespaced harness_options.

    Returns a deterministically-ordered payload frozen into
    ``harness_config_snapshot["options"]``. Invalid typed option values on a
    Profile or Task are rejected at snapshot time so a misconfigured value
    cannot silently reach a Worker.
    """
    raw = getattr(profile, "harness_options", None) or {}
    validated = validate_namespaced_options(raw)
    overrides = validate_task_overrides(task_overrides)
    return deep_merge_options(validated, overrides)


def apply_task_harness_options(
    snapshot: TaskWorkerProfileSnapshot,
    task_overrides: Mapping[str, Any] | None,
) -> TaskWorkerProfileSnapshot:
    """Apply validated Task option overrides to an existing frozen snapshot.

    Pending-task edits must update the immutable execution contract itself; a
    later Worker must never consult the editable Profile to discover an option.
    The existing merged snapshot is used as the base so a partial PATCH keeps
    untouched options stable even though the original Profile is no longer
    needed for the edit.
    """
    config = getattr(snapshot, "harness_config_snapshot", None)
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("Task worker snapshot has an invalid harness config")
    updated = dict(config)
    current_options = updated.get("options")
    if current_options is not None and not isinstance(current_options, dict):
        raise ValueError("Task worker snapshot has invalid harness options")
    updated["options"] = deep_merge_options(
        current_options,
        validate_task_overrides(task_overrides),
    )
    snapshot.harness_config_snapshot = updated
    return snapshot


def snapshot_from_profile(
    task: Task,
    profile: WorkerProfile,
    *,
    settings: Any | None = None,
    harness_key: str | None = None,
    endpoint: Any | None = None,
    shared_configuration: Any | None = None,
    task_harness_options: Mapping[str, Any] | None = None,
) -> TaskWorkerProfileSnapshot:
    """Build an immutable task worker snapshot from a loaded profile.

    ``harness_key`` defaults to the Profile's default harness. ``endpoint`` is a
    secret-free ``ModelEndpoint`` (or any object exposing ``as_snapshot``) whose
    snapshot and credential ref are frozen so later Profile/Provider edits never
    change a created Task's execution truth.

    ``shared_configuration`` is a ``WorkerSharedConfigurationContext``; callers
    that create Task snapshots always pass the loaded shared baseline so the
    per-item merge is applied. When it is ``None`` (direct calls in tests) the
    profile is resolved against an empty baseline. The snapshot stores the fully
    expanded effective configuration plus the shared revision and
    effective-configuration digest.
    """
    effective = resolve_effective_configuration(profile, shared_configuration)
    validate_effective_configuration(effective)
    connection = (
        resolve_docker_connection(
            settings,
            docker_host=getattr(profile, "docker_host", None),
            docker_tls_ca=getattr(profile, "docker_tls_ca", None),
            docker_tls_cert=getattr(profile, "docker_tls_cert", None),
            docker_tls_key=getattr(profile, "docker_tls_key", None),
        )
        if settings is not None
        else None
    )
    resolved_harness_key = (
        harness_key or getattr(profile, "default_harness_key", None) or "claude"
    )
    effective_capabilities = capability_policy(
        resolved_harness_key,
        getattr(profile, "harness_constraints", None) or {},
    )
    harness_runtime = (getattr(profile, "harness_runtimes", None) or {}).get(
        resolved_harness_key, {}
    )
    requested_contract = (
        harness_runtime.get("contract_version", HARNESS_CONTRACT_VERSION)
        if isinstance(harness_runtime, dict)
        else HARNESS_CONTRACT_VERSION
    )
    v2_image_identity = None
    if requested_contract == "codify.worker.harness/v2":
        v2_image_identity = validate_v2_worker_image_identity(
            getattr(profile, "v2_worker_image_identity", None)
        )
        # Content-addressed Worker Kit identity is part of the V2 execution
        # identity (image_identity + kit_identity + bundle_digest). Mounted-kit
        # targets freeze it; baked-image targets have no Kit to freeze.
        if (effective.runtime_mode or BAKED_IMAGE_MODE) == MOUNTED_KIT_MODE:
            v2_kit_identity = validate_v2_worker_kit_identity(
                getattr(profile, "worker_kit_identity", None)
            )
        else:
            v2_kit_identity = None
        current_digest = current_runtime_verification_digest(
            profile, effective, settings or get_effective_settings(), harness_key=resolved_harness_key
        )
        evidence_by_key = getattr(profile, "v2_harness_verification_evidence", None)
        evidence = evidence_by_key.get(resolved_harness_key) if isinstance(evidence_by_key, Mapping) else None
        v2_harness_evidence = validate_v2_harness_evidence(
            evidence,
            harness_key=resolved_harness_key,
            verification_digest=current_digest,
            image_identity=v2_image_identity,
            generation=int(getattr(profile, "v2_worker_image_identity_generation", 0) or 0),
        )
        v2_cli_identity = dict(v2_harness_evidence["cli"])
    else:
        v2_harness_evidence = None
        v2_kit_identity = None
        v2_cli_identity = None
    runtime_locator_fingerprint = fingerprint_from_docker_target(
        settings or get_effective_settings(),
        docker_host=getattr(profile, "docker_host", None),
        docker_tls_ca=getattr(profile, "docker_tls_ca", None),
        docker_tls_cert=getattr(profile, "docker_tls_cert", None),
        docker_tls_key=getattr(profile, "docker_tls_key", None),
        runtime_mode=effective.runtime_mode,
        worker_kit_version=effective.worker_kit_version,
        worker_kit_path=effective.worker_kit_path,
    )
    snapshot = TaskWorkerProfileSnapshot(
        task_id=task.id,
        worker_profile_id=profile.id,
        profile_name=profile.name,
        image=profile.image,
        runtime_mode=effective.runtime_mode,
        worker_kit_version=effective.worker_kit_version,
        worker_kit_path=effective.worker_kit_path,
        docker_host=(connection.host if connection else getattr(profile, "docker_host", None)),
        docker_tls_ca=(
            connection.tls_ca if connection else getattr(profile, "docker_tls_ca", None)
        ),
        docker_tls_cert=(
            connection.tls_cert if connection else getattr(profile, "docker_tls_cert", None)
        ),
        docker_tls_key=(
            connection.tls_key if connection else getattr(profile, "docker_tls_key", None)
        ),
        codegraph_enabled=bool(getattr(profile, "codegraph_enabled", False)),
        volume_mounts=list(effective.volume_mounts),
        environment_variables=list(effective.environment_variables),
        shared_configuration_revision=effective.shared_configuration_revision,
        effective_configuration_digest=None,
        runtime_locator_fingerprint=runtime_locator_fingerprint,
        skill_references=[],
        skill_selection_source="profile",
        pre_script=effective.pre_script,
        post_script=effective.post_script,
        default_execute_run_instruction_template=(
            effective.default_execute_run_instruction_template
        ),
        default_plan_run_instruction_template=effective.default_plan_run_instruction_template,
        ci_auto_repair_run_instruction_template=(
            effective.ci_auto_repair_run_instruction_template
        ),
        harness_key=resolved_harness_key,
        harness_config_snapshot={
            "requested_runtime_contract_version": requested_contract,
            **({_V2_IMAGE_IDENTITY_KEY: v2_image_identity} if v2_image_identity else {}),
            **({_V2_KIT_IDENTITY_KEY: v2_kit_identity} if v2_kit_identity else {}),
            **({_V2_HARNESS_EVIDENCE_KEY: v2_harness_evidence} if v2_harness_evidence else {}),
            "capabilities": effective_capabilities,
            "sandbox_mode": effective_capabilities.get("sandbox_mode"),
            "constraints": dict(getattr(profile, "harness_constraints", None) or {}),
            "options": _freeze_harness_options(profile, task_harness_options),
        },
        image_digest=getattr(profile, "image_digest", None),
        cli_source=(v2_cli_identity or {}).get("source"),
        cli_executable_path=(v2_cli_identity or {}).get("executable_path"),
        cli_version=(v2_cli_identity or {}).get("version"),
        cli_binary_digest=(v2_cli_identity or {}).get("binary_digest"),
        model_endpoint_snapshot=endpoint.as_snapshot() if endpoint is not None else None,
        credential_ref=(
            endpoint.credential_ref
            if endpoint is not None and getattr(endpoint, "credential_ref", None)
            else None
        ),
    )
    # The digest covers the full frozen execution truth including the resolved
    # Docker target and harness decision; skill references are empty here and are
    # folded in by the caller once skills are attached (§10.1).
    snapshot.effective_configuration_digest = snapshot_effective_configuration_digest(
        snapshot
    )
    return snapshot


async def replace_task_worker_snapshot(
    db: AsyncSession,
    task: Task,
    profile: WorkerProfile,
    *,
    harness_key: str | None = None,
    endpoint: Any | None = None,
    shared_configuration: Any | None = None,
    task_harness_options: Mapping[str, Any] | None = None,
) -> TaskWorkerProfileSnapshot:
    """Replace one task's worker profile snapshot.

    ``shared_configuration`` is the caller's already-locked shared context (see
    ``load_shared_configuration(..., for_update=True)``). Task create / F6 switch
    / CI repair pass the same context they used for the readiness gate so the
    snapshot freezes the identical baseline. When omitted the baseline is loaded
    unlocked (retry/clone paths that reuse a frozen snapshot).
    """
    if shared_configuration is None:
        shared = await load_shared_configuration(db)
    else:
        shared = shared_configuration
    existing = await db.get(TaskWorkerProfileSnapshot, task.id)
    if existing is not None:
        await db.delete(existing)
        await db.flush()
    snapshot = snapshot_from_profile(
        task,
        profile,
        settings=get_effective_settings(),
        harness_key=harness_key,
        endpoint=endpoint,
        shared_configuration=shared,
        task_harness_options=task_harness_options,
    )
    db.add(snapshot)
    task.worker_profile_id = profile.id
    await db.flush()
    return snapshot


async def clone_task_worker_snapshot(
    db: AsyncSession,
    *,
    source: TaskWorkerProfileSnapshot,
    target_task: Task,
) -> TaskWorkerProfileSnapshot:
    """Clone execution truth for retry without consulting the editable Profile."""
    try:
        skills_unloaded = "skill_references" in sa_inspect(source).unloaded
    except Exception:
        skills_unloaded = False
    if skills_unloaded:
        await db.refresh(source, attribute_names=["skill_references"])
    snapshot = TaskWorkerProfileSnapshot(
        task_id=target_task.id,
        worker_profile_id=source.worker_profile_id,
        profile_name=source.profile_name,
        image=source.image,
        runtime_mode=source.runtime_mode,
        worker_kit_version=source.worker_kit_version,
        worker_kit_path=source.worker_kit_path,
        docker_host=source.docker_host,
        docker_tls_ca=source.docker_tls_ca,
        docker_tls_cert=source.docker_tls_cert,
        docker_tls_key=source.docker_tls_key,
        codegraph_enabled=source.codegraph_enabled,
        volume_mounts=[dict(item) for item in (source.volume_mounts or [])],
        environment_variables=[dict(item) for item in (source.environment_variables or [])],
        shared_configuration_revision=source.shared_configuration_revision,
        effective_configuration_digest=source.effective_configuration_digest,
        runtime_locator_fingerprint=source.runtime_locator_fingerprint,
        skill_selection_source=source.skill_selection_source,
        pre_script=source.pre_script,
        post_script=source.post_script,
        default_execute_run_instruction_template=source.default_execute_run_instruction_template,
        default_plan_run_instruction_template=source.default_plan_run_instruction_template,
        ci_auto_repair_run_instruction_template=source.ci_auto_repair_run_instruction_template,
        harness_key=source.harness_key,
        harness_adapter_version=source.harness_adapter_version,
        harness_adapter_digest=source.harness_adapter_digest,
        harness_config_snapshot=(
            dict(source.harness_config_snapshot)
            if isinstance(source.harness_config_snapshot, dict)
            else None
        ),
        model_endpoint_snapshot=(
            dict(source.model_endpoint_snapshot)
            if isinstance(source.model_endpoint_snapshot, dict)
            else None
        ),
        credential_ref=source.credential_ref,
        cli_source=source.cli_source,
        cli_executable_path=source.cli_executable_path,
        cli_version=source.cli_version,
        cli_binary_digest=source.cli_binary_digest,
        image_digest=source.image_digest,
        runtime_contract_version=source.runtime_contract_version,
        orchestration_version=source.orchestration_version,
        runtime_bundle_digest=source.runtime_bundle_digest,
        skill_references=[
            TaskSkillVersionReference(
                task_id=target_task.id,
                position=reference.position,
                skill_id=reference.skill_id,
                skill_version_id=reference.skill_version_id,
                name=reference.name,
                description=reference.description,
            )
            for reference in source.skill_references
        ],
    )
    db.add(snapshot)
    target_task.worker_profile_id = source.worker_profile_id
    target_task.worker_profile_snapshot = snapshot
    await db.flush()
    return snapshot


def select_snapshot_run_instruction_template(
    snapshot: TaskWorkerProfileSnapshot,
    *,
    task_mode: str,
    trigger_source: str = "manual",
) -> str:
    """Select the validated run-instruction template from a task snapshot."""
    if trigger_source == "ci_auto_repair":
        return validate_run_instruction_template(snapshot.ci_auto_repair_run_instruction_template)
    if task_mode == "freeform":
        return validate_run_instruction_template(FREEFORM_RUN_INSTRUCTION_TEMPLATE)
    if task_mode == "plan":
        return validate_run_instruction_template(snapshot.default_plan_run_instruction_template)
    return validate_run_instruction_template(snapshot.default_execute_run_instruction_template)


async def load_task_worker_runtime(db: AsyncSession, task: Task) -> TaskWorkerRuntime:
    """Load the immutable runtime fields used by worker execution."""
    snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)
    if snapshot is None:
        raise WorkerProfileValidationError(f"Task {task.id} has no worker profile snapshot")
    # Attach so downstream code can read the frozen harness without a lazy load.
    task.worker_profile_snapshot = snapshot
    try:
        skills_unloaded = "skill_references" in sa_inspect(snapshot).unloaded
    except Exception:
        # Lightweight test doubles do not expose SQLAlchemy inspection state.
        skills_unloaded = False
    if skills_unloaded:
        await db.refresh(snapshot, attribute_names=["skill_references"])
    try:
        hydrated_skills = await hydrate_skill_snapshots(
            db,
            skill_snapshots_from_task_snapshot(snapshot),
        )
    except SkillValidationError as exc:
        raise WorkerProfileValidationError(str(exc)) from exc
    try:
        runtime_mode, kit_version, kit_path = validate_worker_kit_config(
            runtime_mode=getattr(snapshot, "runtime_mode", BAKED_IMAGE_MODE),
            worker_kit_version=getattr(snapshot, "worker_kit_version", None),
            worker_kit_path=getattr(snapshot, "worker_kit_path", None),
        )
        mounts = parse_worker_profile_mounts(snapshot.volume_mounts)
        validate_worker_kit_mounts(runtime_mode, mounts)
        validate_runtime_supports_skills(snapshot, hydrated_skills)
    except (WorkerKitValidationError, SkillValidationError) as exc:
        raise WorkerProfileValidationError(str(exc)) from exc
    return TaskWorkerRuntime(
        image=snapshot.image,
        runtime_mode=runtime_mode,
        worker_kit_version=kit_version,
        worker_kit_path=kit_path,
        codegraph_enabled=bool(getattr(snapshot, "codegraph_enabled", False)),
        volume_mounts=mounts,
        environment=build_worker_profile_environment_map(snapshot.environment_variables),
        pre_script=snapshot.pre_script or "",
        post_script=snapshot.post_script or "",
        skills=hydrated_skills,
        docker_host=getattr(snapshot, "docker_host", None),
        docker_tls_ca=getattr(snapshot, "docker_tls_ca", None),
        docker_tls_cert=getattr(snapshot, "docker_tls_cert", None),
        docker_tls_key=getattr(snapshot, "docker_tls_key", None),
    )


async def replace_profile_environment_variables(
    db: AsyncSession,
    profile: WorkerProfile,
    items: Iterable[Any],
) -> None:
    """Replace all environment variables for one worker profile.

    Each item is ``{key, operation, value, is_secret}`` where ``operation`` is
    ``set`` (profile overrides or adds) or ``mask`` (profile hides a shared
    variable). A ``mask`` row stores no value. The submitted list is the full
    desired state; any stored row whose key is absent is removed, which restores
    inheritance for that key.
    """
    result = await db.execute(
        select(WorkerProfileEnvironmentVariable).where(
            WorkerProfileEnvironmentVariable.worker_profile_id == profile.id
        )
    )
    existing_rows = list(result.scalars().all())
    existing_by_key = {row.key: row for row in existing_rows}
    seen_keys: set[str] = set()

    for item in items:
        key = _validate_environment_key(str(_profile_value(item, "key") or "").strip())
        if key in seen_keys:
            raise WorkerProfileValidationError(
                f"Duplicate worker environment variable key: {key}"
            )
        seen_keys.add(key)

        operation = str(_profile_value(item, "operation", "set") or "set").strip().lower()
        if operation not in {"set", "mask"}:
            raise WorkerProfileValidationError(
                f"Invalid worker environment variable operation: {operation}"
            )
        existing_row = existing_by_key.get(key)

        if operation == "mask":
            if bool(_profile_value(item, "is_secret", False)):
                raise WorkerProfileValidationError(
                    f"Masked worker environment variable {key} cannot be a secret"
                )
            stored_value = None
            is_secret = False
        else:
            value = str(_profile_value(item, "value", "") or "")
            is_secret = bool(_profile_value(item, "is_secret", False))
            if is_secret and value == "":
                if existing_row is None or not existing_row.is_secret:
                    raise WorkerProfileValidationError(
                        f"New secret worker environment variable {key} cannot use a blank value"
                    )
                stored_value = existing_row.value
            else:
                stored_value = serialize_worker_environment_variable_value(
                    value,
                    is_secret=is_secret,
                )

        if existing_row is None:
            db.add(
                WorkerProfileEnvironmentVariable(
                    worker_profile_id=profile.id,
                    key=key,
                    operation=operation,
                    value=stored_value,
                    is_secret=is_secret,
                )
            )
        else:
            existing_row.operation = operation
            existing_row.value = stored_value
            existing_row.is_secret = is_secret

    for row in existing_rows:
        if row.key not in seen_keys:
            await db.delete(row)

    await db.flush()


async def set_default_worker_profile(db: AsyncSession, profile: WorkerProfile) -> None:
    """Mark one enabled worker profile as default and unset all others."""
    if not profile.enabled:
        raise WorkerProfileValidationError("Disabled worker profiles cannot be default")
    await db.execute(update(WorkerProfile).values(is_default=False))
    profile.is_default = True
    await db.flush()


async def disable_worker_profile(db: AsyncSession, profile: WorkerProfile) -> None:
    """Disable a worker profile unless it is the current default."""
    if profile.is_default:
        raise WorkerProfileValidationError("Default worker profile cannot be disabled")
    profile.enabled = False
    await db.flush()
