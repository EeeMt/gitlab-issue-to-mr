#!/usr/bin/env python3
"""Validate the immutable Worker-image CLI identity lock mounted for V2."""

from __future__ import annotations

import json
import hashlib
import os
import pathlib
import re
import sys
from typing import Any


LINUX_PLATFORM_RE = re.compile(r"^linux/[A-Za-z0-9][A-Za-z0-9_.-]*$")


def reject(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def validate(
    lock: Any,
    *,
    expected_platform: str | None = None,
    expected_sha256: str | None = None,
    raw_bytes: bytes | None = None,
) -> None:
    if not isinstance(lock, dict) or lock.get("schema") != "codify.worker.cli-artifacts/v1":
        reject("Worker CLI artifact lock has an unsupported schema")
    platform = lock.get("platform")
    if (
        not isinstance(platform, str) or LINUX_PLATFORM_RE.fullmatch(platform) is None
    ):
        reject("Worker CLI artifact lock has an invalid platform")
    if expected_platform is not None and platform != expected_platform:
        reject(
            "Worker CLI artifact lock platform does not match the selected Docker daemon "
            f"image platform: {platform!r} != {expected_platform!r}"
        )
    if expected_sha256 is not None:
        actual_sha256 = hashlib.sha256(raw_bytes or b"").hexdigest()
        if actual_sha256 != expected_sha256:
            reject("Worker CLI artifact lock bytes do not match the selected Worker image")
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"claude", "codex", "pi", "opencode"}:
        reject("Worker CLI artifact lock must contain exactly four Harness artifacts")
    for key, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            reject(f"Worker CLI artifact lock has an invalid artifact: {key}")
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or set(digest) - set("0123456789abcdef"):
            reject(f"Worker CLI artifact lock has an invalid SHA-256: {key}")
        if not isinstance(artifact.get("version"), str) or not artifact["version"]:
            reject(f"Worker CLI artifact lock has a missing version: {key}")


def _require_readonly_mount(path: pathlib.Path) -> None:
    """Prove the mount itself is read-only without mutating the release lock."""
    readonly_flag = getattr(os, "ST_RDONLY", None)
    try:
        flags = os.statvfs(path).f_flag
    except OSError as exc:
        reject(f"cannot inspect Worker CLI artifact lock mount: {exc}")
    if readonly_flag is None or not flags & readonly_flag:
        reject("Worker CLI artifact lock is not mounted read-only")


def main() -> None:
    arguments = sys.argv[1:]
    require_readonly = False
    expected_platform: str | None = None
    expected_sha256: str | None = None
    while arguments and arguments[0].startswith("--"):
        option = arguments.pop(0)
        if option == "--require-readonly":
            require_readonly = True
        elif option == "--expected-platform":
            if not arguments:
                raise SystemExit("--expected-platform requires a value")
            expected_platform = arguments.pop(0)
        elif option == "--expected-sha256":
            if not arguments:
                raise SystemExit("--expected-sha256 requires a value")
            expected_sha256 = arguments.pop(0)
            if len(expected_sha256) != 64 or set(expected_sha256) - set("0123456789abcdef"):
                raise SystemExit("--expected-sha256 must be a lowercase SHA-256")
        else:
            raise SystemExit(f"unknown option: {option}")
    if len(arguments) != 1:
        raise SystemExit(
            "usage: validate-worker-cli-artifact-lock.py "
            "[--require-readonly] [--expected-platform linux/ARCH] PATH"
        )
    path = pathlib.Path(arguments[0])
    try:
        raw_bytes = path.read_bytes()
        lock = json.loads(raw_bytes)
    except (OSError, ValueError) as exc:
        reject(f"invalid Worker CLI artifact lock: {exc}")
    if require_readonly:
        _require_readonly_mount(path)
    validate(
        lock,
        expected_platform=expected_platform,
        expected_sha256=expected_sha256,
        raw_bytes=raw_bytes,
    )


if __name__ == "__main__":
    main()
