"""Validation and immutable snapshot helpers for Claude Code skills."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re
import stat
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any

import yaml
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload, undefer

from app.core.worker_kit import BAKED_IMAGE_MODE, MOUNTED_KIT_MODE
from app.models import (
    Skill,
    SkillVersion,
    TaskSkillVersionReference,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
    WorkerProfileSkill,
)

MAX_SKILLS_PER_TASK = 20
MAX_SKILL_DESCRIPTION_LENGTH = 1024
MAX_SKILL_MARKDOWN_LENGTH = 100_000
MAX_SKILL_FILES = 128
MAX_SKILL_FILE_BYTES = 2 * 1024 * 1024
MAX_SKILL_FILE_BASE64_LENGTH = ((MAX_SKILL_FILE_BYTES + 2) // 3) * 4
MAX_SKILL_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_TASK_SKILL_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_SKILL_FILE_PATH_LENGTH = 240
SKILL_CAPABLE_WORKER_KIT_VERSION = (0, 3, 5)
SKILL_CAPABLE_WORKER_KIT_VERSION_TEXT = "0.3.5"
# Serialize the low-volume admin mutations that jointly maintain the aggregate
# package limit across Skills and Worker Profiles. This must be acquired before
# either Skill or WorkerProfile rows are locked.
WORKER_PROFILE_SKILL_PACKAGE_LOCK_KEY = 0x434F44494659534B
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SKILL_RESERVED_NAME_PARTS = ("anthropic", "claude")
XML_TAG_PATTERN = re.compile(r"</?[A-Za-z][^>]*>")


class SkillValidationError(ValueError):
    """Raised when a skill or skill selection is invalid."""


def validate_skill_name(value: str) -> str:
    name = value.strip()
    if not SKILL_NAME_PATTERN.fullmatch(name):
        raise SkillValidationError(
            "Skill name must use 1-64 lowercase letters, numbers, or hyphens, "
            "and must start and end with a letter or number"
        )
    if any(part in name for part in SKILL_RESERVED_NAME_PARTS):
        raise SkillValidationError("Skill name cannot contain reserved words 'anthropic' or 'claude'")
    return name


def validate_skill_description(value: str) -> str:
    description = value.strip()
    if not description:
        raise SkillValidationError("Skill description cannot be blank")
    if len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
        raise SkillValidationError(
            f"Skill description must be {MAX_SKILL_DESCRIPTION_LENGTH} characters or fewer"
        )
    if XML_TAG_PATTERN.search(description):
        raise SkillValidationError("Skill description cannot contain XML tags")
    return description


def validate_skill_markdown(
    value: str,
    *,
    expected_name: str | None = None,
) -> tuple[str, str]:
    """Validate a complete SKILL.md while preserving all supported frontmatter fields."""
    if not isinstance(value, str) or not value:
        raise SkillValidationError("SKILL.md cannot be blank")
    if len(value) > MAX_SKILL_MARKDOWN_LENGTH:
        raise SkillValidationError(
            f"SKILL.md must be {MAX_SKILL_MARKDOWN_LENGTH} characters or fewer"
        )

    markdown = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != "---":
        raise SkillValidationError("SKILL.md must start with YAML frontmatter")
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\n") == "---"),
        None,
    )
    if closing_index is None:
        raise SkillValidationError("SKILL.md YAML frontmatter is not closed")
    try:
        frontmatter = yaml.safe_load("".join(lines[1:closing_index])) or {}
    except yaml.YAMLError as exc:
        raise SkillValidationError(f"SKILL.md YAML frontmatter is invalid: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise SkillValidationError("SKILL.md YAML frontmatter must be an object")
    raw_name = frontmatter.get("name")
    if not isinstance(raw_name, str):
        raise SkillValidationError("SKILL.md frontmatter requires a text name")
    name = validate_skill_name(raw_name)
    if expected_name is not None and name != expected_name:
        raise SkillValidationError(
            f"SKILL.md frontmatter name '{name}' must match Skill name '{expected_name}'"
        )
    raw_description = frontmatter.get("description")
    if not isinstance(raw_description, str):
        raise SkillValidationError("SKILL.md frontmatter requires a text description")
    description = validate_skill_description(raw_description)
    if not "".join(lines[closing_index + 1 :]).strip():
        raise SkillValidationError("SKILL.md instructions cannot be blank")
    if not markdown.endswith("\n"):
        markdown += "\n"
    return markdown, description


def validate_skill_file_path(value: str) -> str:
    """Validate a portable relative path inside one immutable skill package."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise SkillValidationError("Skill file path cannot be blank or contain outer whitespace")
    if len(value) > MAX_SKILL_FILE_PATH_LENGTH:
        raise SkillValidationError(
            f"Skill file path must be {MAX_SKILL_FILE_PATH_LENGTH} characters or fewer"
        )
    if "\\" in value or "\x00" in value or value.startswith("/") or value.endswith("/"):
        raise SkillValidationError(f"Invalid skill file path: {value!r}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SkillValidationError(f"Invalid skill file path: {value!r}")
    if parts[0] == "SKILL.md":
        raise SkillValidationError("SKILL.md must be supplied as the package entry point")
    # PurePosixPath is intentionally used even when Codify runs on another host OS.
    normalized = PurePosixPath(*parts).as_posix()
    if normalized != value:
        raise SkillValidationError(f"Invalid skill file path: {value!r}")
    return normalized


def _decode_skill_file(content_base64: str, path: str) -> bytes:
    if not isinstance(content_base64, str):
        raise SkillValidationError(f"Skill file '{path}' content must be base64 text")
    try:
        payload = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SkillValidationError(f"Skill file '{path}' content is not valid base64") from exc
    if len(payload) > MAX_SKILL_FILE_BYTES:
        raise SkillValidationError(
            f"Skill file '{path}' exceeds the {MAX_SKILL_FILE_BYTES}-byte limit"
        )
    return payload


def normalize_skill_files(items: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Validate and canonicalize regular files stored alongside SKILL.md."""
    raw_items = list(items or [])
    if len(raw_items) > MAX_SKILL_FILES:
        raise SkillValidationError(f"A skill can contain at most {MAX_SKILL_FILES} files")

    normalized: list[dict[str, Any]] = []
    payloads_by_path: dict[str, bytes] = {}
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise SkillValidationError("Each skill file must be an object")
        path = validate_skill_file_path(item.get("path"))
        if path in payloads_by_path:
            raise SkillValidationError(f"Duplicate skill file path: {path}")
        executable = item.get("executable", False)
        if not isinstance(executable, bool):
            raise SkillValidationError(f"Skill file '{path}' executable flag must be boolean")
        payload = _decode_skill_file(item.get("content_base64"), path)
        payloads_by_path[path] = payload
        normalized.append(
            {
                "path": path,
                "content_base64": base64.b64encode(payload).decode("ascii"),
                "executable": executable,
            }
        )

    paths = set(payloads_by_path)
    for path in paths:
        for parent in PurePosixPath(path).parents:
            parent_path = parent.as_posix()
            if parent_path != "." and parent_path in paths:
                raise SkillValidationError(
                    f"Skill file '{parent_path}' conflicts with directory '{parent_path}/'"
                )
    total_bytes = sum(len(payload) for payload in payloads_by_path.values())
    if total_bytes > MAX_SKILL_PACKAGE_BYTES:
        raise SkillValidationError(
            f"Skill supporting files exceed the {MAX_SKILL_PACKAGE_BYTES}-byte package limit"
        )
    return sorted(normalized, key=lambda item: item["path"])


def decode_skill_file_content(item: Mapping[str, Any]) -> bytes:
    """Decode one already-normalized package entry for runtime materialization."""
    path = validate_skill_file_path(item.get("path"))
    return _decode_skill_file(item.get("content_base64"), path)


def build_skill_download_archive(
    *,
    name: str,
    skill_md: str,
    files: Iterable[Mapping[str, Any]] | None,
) -> bytes:
    """Build a deterministic, portable ZIP for one validated Skill package."""
    normalized_name = validate_skill_name(name)
    normalized_skill_md, _ = validate_skill_markdown(
        skill_md,
        expected_name=normalized_name,
    )
    normalized_files = normalize_skill_files(files)
    file_payloads = [
        (item, decode_skill_file_content(item)) for item in normalized_files
    ]
    package_size_bytes = len(normalized_skill_md.encode("utf-8")) + sum(
        len(payload) for _, payload in file_payloads
    )
    if package_size_bytes > MAX_SKILL_PACKAGE_BYTES:
        raise SkillValidationError(
            f"Skill package exceeds the {MAX_SKILL_PACKAGE_BYTES}-byte package limit"
        )
    buffer = io.BytesIO()
    written_directories: set[str] = set()

    def write_directory(path: str) -> None:
        archive_path = path.rstrip("/") + "/"
        if archive_path in written_directories:
            return
        info = zipfile.ZipInfo(archive_path, date_time=(1980, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
        archive.writestr(info, b"")
        written_directories.add(archive_path)

    def write_file(path: str, payload: bytes, mode: int) -> None:
        info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (stat.S_IFREG | mode) << 16
        archive.writestr(info, payload)

    with zipfile.ZipFile(buffer, mode="w") as archive:
        root = f"{normalized_name}/"
        write_directory(root)
        write_file(f"{root}SKILL.md", normalized_skill_md.encode("utf-8"), 0o644)
        for item, payload in file_payloads:
            relative_path = PurePosixPath(item["path"])
            parent_paths = list(relative_path.parents)[:-1]
            for parent in reversed(parent_paths):
                write_directory(f"{root}{parent.as_posix()}")
            write_file(
                f"{root}{relative_path.as_posix()}",
                payload,
                0o755 if item["executable"] else 0o644,
            )
    return buffer.getvalue()


def build_skill_version(
    *,
    name: str,
    skill_md: str,
    files: Iterable[Mapping[str, Any]] | None,
) -> SkillVersion:
    """Build one validated immutable package version for persistence."""
    normalized_name = validate_skill_name(name)
    normalized_skill_md, normalized_description = validate_skill_markdown(
        skill_md,
        expected_name=normalized_name,
    )
    normalized_files = normalize_skill_files(files)
    package_size_bytes = len(normalized_skill_md.encode("utf-8")) + sum(
        len(decode_skill_file_content(item)) for item in normalized_files
    )
    if package_size_bytes > MAX_SKILL_PACKAGE_BYTES:
        raise SkillValidationError(
            f"Skill package exceeds the {MAX_SKILL_PACKAGE_BYTES}-byte package limit"
        )
    canonical = json.dumps(
        {
            "name": normalized_name,
            "description": normalized_description,
            "skill_md": normalized_skill_md,
            "files": normalized_files,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return SkillVersion(
        name=normalized_name,
        description=normalized_description,
        skill_md=normalized_skill_md,
        files=normalized_files,
        package_size_bytes=package_size_bytes,
        digest=hashlib.sha256(canonical).hexdigest(),
    )


def normalize_skill_ids(skill_ids: Iterable[int]) -> list[int]:
    normalized = list(skill_ids)
    if len(normalized) > MAX_SKILLS_PER_TASK:
        raise SkillValidationError(f"At most {MAX_SKILLS_PER_TASK} skills can be selected")
    if len(set(normalized)) != len(normalized):
        raise SkillValidationError("Duplicate skill IDs are not allowed")
    if any(not isinstance(skill_id, int) or isinstance(skill_id, bool) or skill_id <= 0 for skill_id in normalized):
        raise SkillValidationError("Skill IDs must be positive integers")
    return normalized


def _version_tuple(value: str | None) -> tuple[int, int, int] | None:
    parts = (value or "").strip().split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def validate_runtime_supports_skills(runtime: Any, skills: Iterable[Any]) -> None:
    """Reject runtimes that would silently ignore a non-empty task skill snapshot."""
    if not list(skills):
        return
    runtime_mode = getattr(runtime, "runtime_mode", BAKED_IMAGE_MODE)
    if runtime_mode != MOUNTED_KIT_MODE:
        raise SkillValidationError(
            "Claude skills require mounted-kit mode; baked-image mode is deprecated "
            "and does not support skills"
        )
    version = _version_tuple(getattr(runtime, "worker_kit_version", None))
    if version is None or version < SKILL_CAPABLE_WORKER_KIT_VERSION:
        raise SkillValidationError(
            "Claude skills require worker-kit "
            f"{SKILL_CAPABLE_WORKER_KIT_VERSION_TEXT} or newer for mounted-kit profiles"
        )


def runtime_uses_skill_capable_worker_kit(runtime: Any) -> bool:
    """Return whether runtime verification must enforce Claude Skill support."""
    if getattr(runtime, "runtime_mode", BAKED_IMAGE_MODE) != MOUNTED_KIT_MODE:
        return False
    version = _version_tuple(getattr(runtime, "worker_kit_version", None))
    return version is not None and version >= SKILL_CAPABLE_WORKER_KIT_VERSION


async def acquire_worker_profile_skill_package_lock(db: AsyncSession) -> None:
    """Acquire the PostgreSQL transaction lock guarding aggregate package limits."""
    bind = db.get_bind()
    if getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": WORKER_PROFILE_SKILL_PACKAGE_LOCK_KEY},
    )


def serialize_skill_snapshot(skill: Skill) -> dict[str, Any]:
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "version_id": skill.current_version_id,
    }


def normalize_skill_snapshots(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for item in items:
        name = validate_skill_name(str(item.get("name") or ""))
        if name in seen_names:
            raise SkillValidationError(f"Duplicate skill name in task snapshot: {name}")
        seen_names.add(name)
        raw_id = item.get("id")
        raw_version_id = item.get("version_id")
        version_id = (
            raw_version_id
            if isinstance(raw_version_id, int)
            and not isinstance(raw_version_id, bool)
            and raw_version_id > 0
            else None
        )
        snapshot = {
            "id": raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None,
            "name": name,
            "description": validate_skill_description(str(item.get("description") or "")),
            "version_id": version_id,
        }
        if "skill_md" in item:
            skill_md, skill_md_description = validate_skill_markdown(
                str(item.get("skill_md") or ""),
                expected_name=name,
            )
            if skill_md_description != snapshot["description"]:
                raise SkillValidationError(
                    f"Skill snapshot '{name}' description does not match SKILL.md"
                )
            snapshot["skill_md"] = skill_md
            snapshot["files"] = normalize_skill_files(item.get("files") or [])
        elif version_id is None:
            raise SkillValidationError(f"Skill snapshot '{name}' has no immutable version")
        snapshots.append(snapshot)
    if len(snapshots) > MAX_SKILLS_PER_TASK:
        raise SkillValidationError(f"At most {MAX_SKILLS_PER_TASK} skills can be selected")
    return snapshots


async def hydrate_skill_snapshots(
    db: AsyncSession,
    items: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve lightweight task references into complete immutable package versions."""
    snapshots = normalize_skill_snapshots(items)
    version_ids = {
        snapshot["version_id"]
        for snapshot in snapshots
        if "skill_md" not in snapshot and snapshot["version_id"] is not None
    }
    versions_by_id: dict[int, SkillVersion] = {}
    if version_ids:
        result = await db.execute(
            select(SkillVersion)
            .options(undefer(SkillVersion.skill_md), undefer(SkillVersion.files))
            .where(SkillVersion.id.in_(version_ids))
        )
        versions_by_id = {version.id: version for version in result.scalars().all()}

    hydrated: list[dict[str, Any]] = []
    total_package_bytes = 0
    for snapshot in snapshots:
        if "skill_md" in snapshot:
            total_package_bytes += len(snapshot["skill_md"].encode("utf-8")) + sum(
                len(decode_skill_file_content(item)) for item in snapshot["files"]
            )
            hydrated.append(snapshot)
            continue
        version_id = snapshot["version_id"]
        version = versions_by_id.get(version_id)
        if version is None:
            raise SkillValidationError(
                f"Skill snapshot '{snapshot['name']}' references missing version {version_id}"
            )
        if version.name != snapshot["name"] or version.description != snapshot["description"]:
            raise SkillValidationError(
                f"Skill snapshot '{snapshot['name']}' does not match version {version_id}"
            )
        hydrated.append(
            {
                **snapshot,
                "skill_md": validate_skill_markdown(
                    version.skill_md,
                    expected_name=version.name,
                )[0],
                "files": normalize_skill_files(version.files),
            }
        )
        total_package_bytes += version.package_size_bytes
    if total_package_bytes > MAX_TASK_SKILL_PACKAGE_BYTES:
        raise SkillValidationError(
            "Selected skill packages exceed the "
            f"{MAX_TASK_SKILL_PACKAGE_BYTES}-byte per-task limit"
        )
    return hydrated


async def load_enabled_skill_snapshots(
    db: AsyncSession,
    skill_ids: Iterable[int],
) -> list[dict[str, Any]]:
    ids = normalize_skill_ids(skill_ids)
    if not ids:
        return []
    result = await db.execute(
        select(Skill)
        .options(
            selectinload(Skill.current_version).options(
                load_only(SkillVersion.id, SkillVersion.package_size_bytes)
            )
        )
        .where(Skill.id.in_(ids))
        .order_by(Skill.id.asc())
        .with_for_update()
    )
    skills_by_id = {skill.id: skill for skill in result.scalars().all()}
    missing = [skill_id for skill_id in ids if skill_id not in skills_by_id]
    if missing:
        raise SkillValidationError(f"Skill {missing[0]} was not found")
    disabled = [skills_by_id[skill_id] for skill_id in ids if not skills_by_id[skill_id].enabled]
    if disabled:
        raise SkillValidationError(f"Skill '{disabled[0].name}' is disabled")
    total_package_bytes = sum(
        skills_by_id[skill_id].current_version.package_size_bytes for skill_id in ids
    )
    if total_package_bytes > MAX_TASK_SKILL_PACKAGE_BYTES:
        raise SkillValidationError(
            "Selected skill packages exceed the "
            f"{MAX_TASK_SKILL_PACKAGE_BYTES}-byte per-task limit"
        )
    return [serialize_skill_snapshot(skills_by_id[skill_id]) for skill_id in ids]


async def resolve_task_skill_snapshots(
    db: AsyncSession,
    worker_profile: Any,
    requested_skill_ids: list[int] | None,
) -> list[dict[str, Any]]:
    """Resolve task override or enabled profile defaults into immutable content."""
    if requested_skill_ids is not None:
        snapshots = await load_enabled_skill_snapshots(db, requested_skill_ids)
    else:
        default_ids = [
            skill.id
            for skill in (getattr(worker_profile, "default_skills", None) or [])
            if bool(getattr(skill, "enabled", False))
        ]
        snapshots = await load_enabled_skill_snapshots(db, default_ids)
    validate_runtime_supports_skills(worker_profile, snapshots)
    return snapshots


async def load_worker_profile_skills(
    db: AsyncSession,
    skill_ids: Iterable[int],
    *,
    retained_disabled_skill_ids: Iterable[int] = (),
) -> list[Skill]:
    """Load a Profile selection while allowing only retained disabled references."""
    ids = normalize_skill_ids(skill_ids)
    if not ids:
        return []
    retained_disabled_ids = set(retained_disabled_skill_ids)
    result = await db.execute(
        select(Skill)
        .options(
            selectinload(Skill.current_version).options(
                load_only(SkillVersion.id, SkillVersion.package_size_bytes)
            )
        )
        .where(Skill.id.in_(ids))
        .order_by(Skill.id.asc())
        .with_for_update()
    )
    skills_by_id = {skill.id: skill for skill in result.scalars().all()}
    missing = [skill_id for skill_id in ids if skill_id not in skills_by_id]
    if missing:
        raise SkillValidationError(f"Skill {missing[0]} was not found")
    disabled = [
        skills_by_id[skill_id]
        for skill_id in ids
        if not skills_by_id[skill_id].enabled and skill_id not in retained_disabled_ids
    ]
    if disabled:
        raise SkillValidationError(f"Skill '{disabled[0].name}' is disabled")
    total_package_bytes = sum(
        skills_by_id[skill_id].current_version.package_size_bytes
        for skill_id in ids
        if skills_by_id[skill_id].enabled
    )
    if total_package_bytes > MAX_TASK_SKILL_PACKAGE_BYTES:
        raise SkillValidationError(
            "Selected skill packages exceed the "
            f"{MAX_TASK_SKILL_PACKAGE_BYTES}-byte per-task limit"
        )
    return [skills_by_id[skill_id] for skill_id in ids]


async def load_enabled_skills(db: AsyncSession, skill_ids: Iterable[int]) -> list[Skill]:
    """Load an ordered enabled-only selection for a new mutable Profile."""
    return await load_worker_profile_skills(db, skill_ids)


async def validate_worker_profile_skill_package_limits(
    db: AsyncSession,
    skill: Skill,
    replacement_version: SkillVersion,
    *,
    target_enabled: bool | None = None,
) -> None:
    """Keep every affected Worker Profile within the per-task package ceiling."""
    result = await db.execute(
        select(WorkerProfile)
        .join(
            WorkerProfileSkill,
            WorkerProfileSkill.worker_profile_id == WorkerProfile.id,
        )
        .where(WorkerProfileSkill.skill_id == skill.id)
        .options(
            selectinload(WorkerProfile.default_skills).selectinload(Skill.current_version)
        )
        .order_by(WorkerProfile.id.asc())
    )
    for profile in result.scalars().unique().all():
        total_package_bytes = 0
        for default_skill in profile.default_skills:
            enabled = (
                target_enabled
                if default_skill.id == skill.id and target_enabled is not None
                else default_skill.enabled
            )
            if not enabled:
                continue
            total_package_bytes += (
                replacement_version.package_size_bytes
                if default_skill.id == skill.id
                else default_skill.current_version.package_size_bytes
            )
        if total_package_bytes > MAX_TASK_SKILL_PACKAGE_BYTES:
            raise SkillValidationError(
                f"Updating Skill '{replacement_version.name}' would make Worker Profile "
                f"'{profile.name}' exceed the {MAX_TASK_SKILL_PACKAGE_BYTES}-byte "
                "per-task package limit"
            )


def skill_snapshots_from_task_snapshot(
    snapshot: TaskWorkerProfileSnapshot,
) -> list[dict[str, Any]]:
    """Serialize ordered relational references into the lightweight snapshot contract."""
    return [
        {
            "id": reference.skill_id,
            "name": reference.name,
            "description": reference.description,
            "version_id": reference.skill_version_id,
        }
        for reference in (getattr(snapshot, "skill_references", None) or [])
    ]


def replace_task_skill_references(
    snapshot: TaskWorkerProfileSnapshot,
    items: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Replace a task snapshot's ordered FK-backed immutable Skill references."""
    snapshots = normalize_skill_snapshots(items)
    existing_by_position = {
        reference.position: reference
        for reference in (getattr(snapshot, "skill_references", None) or [])
    }
    references: list[TaskSkillVersionReference] = []
    for position, item in enumerate(snapshots):
        version_id = item.get("version_id")
        if not isinstance(version_id, int):
            raise SkillValidationError(
                f"Skill snapshot '{item['name']}' has no persistent immutable version"
            )
        reference = existing_by_position.get(position) or TaskSkillVersionReference(
            position=position
        )
        reference.skill_id = item.get("id") if isinstance(item.get("id"), int) else None
        reference.skill_version_id = version_id
        reference.name = item["name"]
        reference.description = item["description"]
        references.append(reference)
    snapshot.skill_references = references
    return snapshots


async def delete_unreferenced_skill_versions(db: AsyncSession) -> int:
    """Delete package versions that are neither current nor referenced by a task."""
    current_version_exists = (
        select(Skill.id).where(Skill.current_version_id == SkillVersion.id).exists()
    )
    task_reference_exists = (
        select(TaskSkillVersionReference.task_id)
        .where(TaskSkillVersionReference.skill_version_id == SkillVersion.id)
        .exists()
    )
    result = await db.execute(
        delete(SkillVersion).where(
            ~current_version_exists,
            ~task_reference_exists,
        )
    )
    return int(result.rowcount or 0)


def render_skill_markdown(snapshot: Mapping[str, Any]) -> str:
    """Return the complete validated SKILL.md entry point without dropping metadata."""
    name = validate_skill_name(str(snapshot.get("name") or ""))
    skill_md, description = validate_skill_markdown(
        str(snapshot.get("skill_md") or ""),
        expected_name=name,
    )
    if description != validate_skill_description(str(snapshot.get("description") or "")):
        raise SkillValidationError("Skill snapshot description does not match SKILL.md")
    return skill_md
