"""Mounted worker-kit runtime contract.

The project runtime image owns project toolchains. Codify-owned tools are delivered as
an immutable, versioned host directory and mounted into the task container.
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from typing import Any, Mapping

BAKED_IMAGE_MODE = "baked_image"
MOUNTED_KIT_MODE = "mounted_kit"
WORKER_RUNTIME_MODES = frozenset({BAKED_IMAGE_MODE, MOUNTED_KIT_MODE})

KIT_CONTAINER_PATH = "/opt/codify-kit"
KIT_STORE_CONTAINER_PATH = "/nix/store"
KIT_ENTRYPOINT = f"{KIT_CONTAINER_PATH}/launcher"
KIT_CONTAINER_USER = "0:0"

_KIT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PROTECTED_KIT_PATHS = (KIT_CONTAINER_PATH, KIT_STORE_CONTAINER_PATH)


class WorkerKitValidationError(ValueError):
    """Raised when a mounted worker-kit configuration is invalid."""


def validate_worker_kit_config(
    *,
    runtime_mode: str | None,
    worker_kit_version: str | None,
    worker_kit_path: str | None,
) -> tuple[str, str | None, str | None]:
    """Normalize one profile's worker delivery mode and kit coordinates."""
    mode = (runtime_mode or BAKED_IMAGE_MODE).strip()
    if mode not in WORKER_RUNTIME_MODES:
        raise WorkerKitValidationError(
            f"runtime_mode must be one of: {', '.join(sorted(WORKER_RUNTIME_MODES))}"
        )

    version = (worker_kit_version or "").strip() or None
    path = (worker_kit_path or "").strip() or None
    if mode == BAKED_IMAGE_MODE:
        if version is not None or path is not None:
            raise WorkerKitValidationError(
                "worker_kit_version and worker_kit_path require mounted_kit mode"
            )
        return mode, None, None

    if version is None or not _KIT_VERSION_PATTERN.fullmatch(version):
        raise WorkerKitValidationError(
            "mounted_kit mode requires a simple worker_kit_version"
        )
    if path is None or not os.path.isabs(path):
        raise WorkerKitValidationError(
            "mounted_kit mode requires an absolute worker_kit_path on the Docker host"
        )
    normalized_path = os.path.normpath(path)
    if normalized_path == os.path.sep:
        raise WorkerKitValidationError(
            "worker_kit_path must not be the Docker host filesystem root"
        )
    return mode, version, normalized_path


def worker_kit_mounts(worker_kit_path: str) -> dict[str, dict[str, str]]:
    """Build the two read-only mounts required by a Nix-closure worker kit."""
    root = os.path.normpath(worker_kit_path)
    return {
        root: {"bind": KIT_CONTAINER_PATH, "mode": "ro"},
        os.path.join(root, "nix", "store"): {
            "bind": KIT_STORE_CONTAINER_PATH,
            "mode": "ro",
        },
    }


def worker_kit_environment(version: str) -> dict[str, str]:
    return {
        "CODIFY_WORKER_RUNTIME_MODE": MOUNTED_KIT_MODE,
        "CODIFY_KIT_HOME": KIT_CONTAINER_PATH,
        "CODIFY_KIT_VERSION": version,
    }


def validate_no_worker_kit_mount_collision(mounts: list[Mapping[str, Any]]) -> None:
    """Reject custom destinations that would hide all or part of the kit mounts."""
    for mount in mounts:
        raw_path = str(mount.get("container_path") or "").strip()
        if not raw_path.startswith("/"):
            continue
        path = PurePosixPath(raw_path)
        for protected_raw in _PROTECTED_KIT_PATHS:
            protected = PurePosixPath(protected_raw)
            if path == protected or path in protected.parents or protected in path.parents:
                raise WorkerKitValidationError(
                    f"custom mount path {raw_path} conflicts with worker-kit path "
                    f"{protected_raw}"
                )


def validate_worker_kit_mounts(
    runtime_mode: str,
    mounts: list[Mapping[str, Any]],
) -> None:
    if runtime_mode == MOUNTED_KIT_MODE:
        validate_no_worker_kit_mount_collision(mounts)
