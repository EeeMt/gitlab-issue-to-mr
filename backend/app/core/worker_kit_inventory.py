"""Worker Kit harness inventory: availability model and fail-closed integrity.

The Kit manifest (``codify.worker.kit-manifest/v1``) carries a
``harness_inventory`` object that always records all four built-in keys:

.. code-block:: json

    {
      "pi":       {"availability": "present", "path": "/opt/codify-kit/harness/pi/bin/pi",
                   "version": "0.84.2", "sha256": "<64hex>", "size": 1234},
      "opencode": {"availability": "absent", "reason_code": "not_selected"}
    }

Rules (architecture contract §11.2):

- ``absent`` entries carry only a stable ``reason_code``: ``not_selected``
  (build selection excluded the key; expected, info level) or
  ``missing_payload`` (selected but the payload failed to be embedded;
  warning level, degraded Kit). They never declare a payload path/version.
- ``present`` entries carry an absolute container path under
  ``KIT_CONTAINER_PATH``, plus version/sha256/size verified at install and
  probe time.
- Structural conflicts (absent-with-payload-fields, unknown keys, unsafe
  paths) are rejected here; content mismatches found while probing the actual
  Kit bytes fail the whole Kit closed in ``worker_runtime_readiness``.

The manifest bytes remain the content-addressed Kit identity: their SHA-256 is
recorded as ``kit_identity.manifest_sha256`` and frozen into Profiles, Task
snapshots and Runtime Bundles.  The manifest also carries a canonical
``content_inventory`` for every execution-bearing file, so its identity
commits to the complete Kit rather than only to the harness payload rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import stat as stat_module
from pathlib import PurePosixPath
from typing import Any, Mapping

from app.core.harness_registry import HARNESS_KEYS
from app.core.worker_kit import KIT_CONTAINER_PATH

INVENTORY_SCHEMA = "codify.worker.kit-inventory/v1"
KIT_IDENTITY_SCHEMA = "codify.worker.kit-identity/v1"
_HEX_DIGITS = frozenset("0123456789abcdef")
_PLATFORM_RE = re.compile(r"^linux/[A-Za-z0-9][A-Za-z0-9_.-]*$")
AVAILABILITY_PRESENT = "present"
AVAILABILITY_ABSENT = "absent"
AVAILABILITIES = frozenset({AVAILABILITY_PRESENT, AVAILABILITY_ABSENT})

REASON_NOT_SELECTED = "not_selected"
REASON_MISSING_PAYLOAD = "missing_payload"
ABSENT_REASON_CODES = frozenset({REASON_NOT_SELECTED, REASON_MISSING_PAYLOAD})

PRESENT_FIELDS = ("path", "version", "sha256", "size")
ABSENT_FIELDS = ("reason_code",)


class HarnessInventoryError(ValueError):
    """Raised when a Kit manifest harness inventory is structurally invalid."""


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and not (set(value) - _HEX_DIGITS)


_CONTENT_INVENTORY_EXCLUDED = frozenset({"manifest.json", ".install-receipt.json", ".smoke-passed"})


def _content_symlink_target(path: str, target: object) -> str:
    if not isinstance(target, str) or not target or target.startswith("/") or "\\" in target:
        raise HarnessInventoryError(f"Kit symlink target is unsafe: {path!r}")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    if (
        not resolved
        or resolved in {".", ".."}
        or resolved.startswith("../")
        or resolved.startswith("/")
        or any(part in {"", ".", ".."} for part in resolved.split("/"))
    ):
        raise HarnessInventoryError(f"Kit symlink target escapes its root: {path!r}")
    return resolved


def content_inventory_digest(entries: list[dict[str, Any]]) -> str:
    """Hash canonical content entries without including generated metadata."""
    canonical = sorted(entries, key=lambda entry: entry["path"])
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def validate_content_inventory(raw: object) -> list[dict[str, Any]]:
    """Validate the full Kit content inventory committed by ``manifest.json``."""
    if not isinstance(raw, list) or not raw:
        raise HarnessInventoryError("Kit content_inventory must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise HarnessInventoryError("Kit content_inventory entries must be objects")
        path = entry.get("path")
        if not isinstance(path, str) or not path or path != posixpath.normpath(path):
            raise HarnessInventoryError("Kit content_inventory path is invalid")
        if (
            path in _CONTENT_INVENTORY_EXCLUDED
            or path.startswith("/")
            or path.startswith("../")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise HarnessInventoryError(f"Kit content_inventory path is unsafe: {path!r}")
        if path in seen:
            raise HarnessInventoryError(f"Kit content_inventory path is duplicated: {path!r}")
        seen.add(path)
        kind = entry.get("kind")
        if kind == "file":
            if set(entry) != {"kind", "path", "sha256", "size"}:
                raise HarnessInventoryError(f"Kit file inventory entry is malformed: {path!r}")
            size = entry.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise HarnessInventoryError(f"Kit file inventory size is invalid: {path!r}")
            sha256 = entry.get("sha256")
            if not _is_sha256(sha256):
                raise HarnessInventoryError(f"Kit file inventory SHA-256 is invalid: {path!r}")
            normalized.append({"kind": "file", "path": path, "sha256": sha256, "size": size})
        elif kind == "symlink":
            if set(entry) != {"kind", "path", "target"} or not isinstance(entry.get("target"), str):
                raise HarnessInventoryError(f"Kit symlink inventory entry is malformed: {path!r}")
            _content_symlink_target(path, entry["target"])
            normalized.append({"kind": "symlink", "path": path, "target": entry["target"]})
        else:
            raise HarnessInventoryError(f"Kit content inventory kind is invalid: {path!r}")
    normalized.sort(key=lambda entry: entry["path"])
    return normalized


def validate_harness_inventory(raw: object) -> dict[str, dict[str, Any]]:
    """Validate and normalize one Kit manifest ``harness_inventory`` object.

    Returns a deep-copied normalized mapping keyed by all four harness keys.
    Raises :class:`HarnessInventoryError` on any structural violation so a
    conflicting Kit fails closed instead of degrading silently.
    """
    if not isinstance(raw, Mapping):
        raise HarnessInventoryError("Kit harness_inventory must be an object")
    keys = set(raw)
    if keys != set(HARNESS_KEYS):
        missing = sorted(set(HARNESS_KEYS) - keys)
        unknown = sorted(keys - set(HARNESS_KEYS))
        raise HarnessInventoryError(
            f"Kit harness_inventory must record exactly {sorted(HARNESS_KEYS)}; "
            f"missing={missing}, unknown={unknown}"
        )
    normalized: dict[str, dict[str, Any]] = {}
    for key in HARNESS_KEYS:
        entry = raw[key]
        if not isinstance(entry, Mapping):
            raise HarnessInventoryError(f"harness_inventory[{key!r}] must be an object")
        availability = entry.get("availability")
        if availability not in AVAILABILITIES:
            raise HarnessInventoryError(
                f"harness_inventory[{key!r}].availability must be {sorted(AVAILABILITIES)}"
            )
        allowed = set(PRESENT_FIELDS if availability == AVAILABILITY_PRESENT else ABSENT_FIELDS)
        allowed.add("availability")
        unknown_fields = set(entry) - allowed
        if unknown_fields:
            raise HarnessInventoryError(
                f"harness_inventory[{key!r}] ({availability}) has forbidden "
                f"fields: {sorted(unknown_fields)}"
            )
        if availability == AVAILABILITY_ABSENT:
            reason = entry.get("reason_code")
            if reason not in ABSENT_REASON_CODES:
                raise HarnessInventoryError(
                    f"harness_inventory[{key!r}].reason_code must be {sorted(ABSENT_REASON_CODES)}"
                )
            normalized[key] = {"availability": AVAILABILITY_ABSENT, "reason_code": reason}
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.startswith(f"{KIT_CONTAINER_PATH}/"):
            raise HarnessInventoryError(
                f"harness_inventory[{key!r}].path must be an absolute container "
                f"path under {KIT_CONTAINER_PATH}"
            )
        relative = kit_relative_path(path)
        if relative is None:
            raise HarnessInventoryError(
                f"harness_inventory[{key!r}].path is not a safe kit-relative path"
            )
        version = entry.get("version")
        if not isinstance(version, str) or not version.strip():
            raise HarnessInventoryError(
                f"harness_inventory[{key!r}].version must be a non-empty string"
            )
        sha256 = entry.get("sha256")
        size = entry.get("size")
        if not _is_sha256(sha256):
            raise HarnessInventoryError(
                f"harness_inventory[{key!r}].sha256 must be a lowercase hex SHA-256"
            )
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise HarnessInventoryError(
                f"harness_inventory[{key!r}].size must be a positive integer"
            )
        normalized[key] = {
            "availability": AVAILABILITY_PRESENT,
            "path": path,
            "version": version,
            "sha256": sha256,
            "size": size,
        }
    return normalized


def kit_relative_path(container_path: str) -> str | None:
    """Map a container inventory path to a safe kit-relative POSIX path."""
    prefix = f"{KIT_CONTAINER_PATH}/"
    if not container_path.startswith(prefix):
        return None
    raw_relative = container_path[len(prefix) :]
    if not raw_relative or raw_relative != raw_relative.strip() or "\\" in raw_relative:
        return None
    if any(part in {"", "."} for part in raw_relative.split("/")):
        return None
    # Reject any ".." component in the raw path: normpath would collapse
    # "harness/pi/../../bin/sh" into the kit root, silently turning a
    # traversal into a safe-looking path.
    if any(part == ".." for part in raw_relative.split("/")):
        return None
    normalized = posixpath.normpath(raw_relative)
    if normalized in {".", ".."} or normalized.startswith("../"):
        return None
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part == ".." for part in pure.parts):
        return None
    return normalized


def missing_payload_warnings(
    inventory: Mapping[str, Mapping[str, Any]],
    *,
    kit_version: str | None,
    kit_identity_digest: str | None = None,
) -> list[dict[str, Any]]:
    """Sanitized ``missing_payload`` warnings for one degraded Kit.

    Warnings never contain tokens, environment values, payloads or native
    diagnostics; they identify the degraded key and the stable reason only.
    """
    warnings: list[dict[str, Any]] = []
    for key in HARNESS_KEYS:
        entry = inventory.get(key)
        if not isinstance(entry, Mapping):
            continue
        if (
            entry.get("availability") == AVAILABILITY_ABSENT
            and entry.get("reason_code") == REASON_MISSING_PAYLOAD
        ):
            warning: dict[str, Any] = {
                "type": "missing_payload",
                "harness_key": key,
                "availability": AVAILABILITY_ABSENT,
                "reason_code": REASON_MISSING_PAYLOAD,
            }
            if kit_version is not None:
                warning["kit_version"] = kit_version
            if kit_identity_digest is not None:
                warning["kit_manifest_sha256"] = kit_identity_digest
            warnings.append(warning)
    return warnings


def kit_identity_from_manifest_bytes(
    manifest_bytes: bytes,
    *,
    require_content_inventory: bool = True,
) -> dict[str, str]:
    """Content-address one Kit build by its exact manifest bytes.

    Any change to the selection set, a payload, the nix closure or any other
    manifest field changes these bytes and therefore the identity. V2 callers
    require the canonical full-content inventory; the legacy V1 compatibility
    probe may explicitly disable that requirement during dual-canary.
    """
    try:
        text = manifest_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HarnessInventoryError("Kit manifest.json is not valid UTF-8") from exc
    try:
        manifest = json.loads(text)
    except ValueError as exc:
        raise HarnessInventoryError("Kit manifest.json is not valid JSON") from exc
    if not isinstance(manifest, Mapping):
        raise HarnessInventoryError("Kit manifest.json must be an object")
    kit_version = manifest.get("kit_version")
    platform = manifest.get("platform")
    if not isinstance(kit_version, str) or not kit_version.strip():
        raise HarnessInventoryError("Kit manifest.json has no kit_version")
    if not isinstance(platform, str) or _PLATFORM_RE.fullmatch(platform) is None:
        raise HarnessInventoryError("Kit manifest.json has no linux/* platform")
    if require_content_inventory:
        entries = validate_content_inventory(manifest.get("content_inventory"))
        declared_content_digest = manifest.get("content_inventory_sha256")
        if (
            not _is_sha256(declared_content_digest)
            or declared_content_digest != content_inventory_digest(entries)
        ):
            raise HarnessInventoryError("Kit manifest.json content inventory digest is invalid")
    return {
        "schema": KIT_IDENTITY_SCHEMA,
        "kit_version": kit_version,
        "platform": platform,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }


def validate_worker_kit_identity(identity: object) -> dict[str, str]:
    """Validate a frozen Worker Kit identity record fail-closed."""
    if not isinstance(identity, Mapping) or identity.get("schema") != KIT_IDENTITY_SCHEMA:
        raise HarnessInventoryError("record is not a codify.worker.kit-identity/v1 document")
    required = ("kit_version", "platform", "manifest_sha256")
    normalized = {key: identity.get(key) for key in required}
    if not all(isinstance(value, str) and value for value in normalized.values()):
        raise HarnessInventoryError("Worker Kit identity is incomplete")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", normalized["kit_version"]) is None:
        raise HarnessInventoryError("Worker Kit identity has an invalid kit_version")
    if _PLATFORM_RE.fullmatch(normalized["platform"]) is None:
        raise HarnessInventoryError("Worker Kit identity has an invalid platform")
    if not _is_sha256(normalized["manifest_sha256"]):
        raise HarnessInventoryError("Worker Kit identity has an invalid manifest SHA-256")
    return {"schema": KIT_IDENTITY_SCHEMA, **normalized}


def local_inventory_problems(
    inventory: Mapping[str, Mapping[str, Any]],
    *,
    kit_root: Any,
) -> list[str]:
    """Verify present inventory entries against an extracted Kit directory.

    Used by installer/preflight tooling and tests. Each present entry must be
    a regular file inside the kit root (no symlink escape), executable, and
    byte-identical to its recorded size and SHA-256. Absent entries are not
    checked on disk: the build system guarantees unselected payloads were
    never copied, and a stray file cannot be identified without a declared
    expectation.
    """
    problems: list[str] = []
    root = PurePosixPath(posixpath.normpath(str(kit_root)))
    for key in HARNESS_KEYS:
        entry = inventory.get(key)
        if not isinstance(entry, Mapping):
            continue
        if entry.get("availability") != AVAILABILITY_PRESENT:
            continue
        relative = kit_relative_path(str(entry.get("path") or ""))
        if relative is None:
            problems.append(f"harness {key}: unsafe inventory path")
            continue
        host_path = posixpath.join(str(root), relative)
        resolved = PurePosixPath(posixpath.normpath(host_path))
        if root != resolved and root not in resolved.parents:
            problems.append(f"harness {key}: path escapes the kit root")
            continue
        try:
            stat_result = os.lstat(host_path)
        except FileNotFoundError:
            problems.append(f"harness {key}: present file {relative} is missing")
            continue
        if stat_module.S_ISLNK(stat_result.st_mode):
            problems.append(f"harness {key}: present file {relative} is a symlink")
            continue
        if not stat_module.S_ISREG(stat_result.st_mode):
            problems.append(f"harness {key}: present path {relative} is not a regular file")
            continue
        if not stat_result.st_mode & stat_module.S_IXUSR:
            problems.append(f"harness {key}: present file {relative} is not executable")
            continue
        declared_size = int(entry.get("size") or 0)
        if stat_result.st_size != declared_size:
            problems.append(
                f"harness {key}: size mismatch for {relative}: "
                f"expected {declared_size}, found {stat_result.st_size}"
            )
            continue
        digest = hashlib.sha256()
        with open(host_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != entry.get("sha256"):
            problems.append(f"harness {key}: sha256 mismatch for {relative}")
    return problems
