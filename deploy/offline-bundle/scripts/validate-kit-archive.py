#!/usr/bin/env python3
"""Reject unsafe worker-kit tar members before any extraction."""

from __future__ import annotations

import posixpath
import sys
import tarfile

NIX_STORE_PREFIX = "/nix/store"


def fail(message: str) -> int:
    print(f"Worker Kit archive is unsafe: {message}", file=sys.stderr)
    return 1


def validate(archive: str, root: str) -> int:
    root = root.rstrip("/")
    if not root or "/" in root or root in {".", ".."}:
        return fail("invalid expected root")
    try:
        with tarfile.open(archive, "r:*") as bundle:
            members = bundle.getmembers()
    except (OSError, tarfile.TarError) as exc:
        return fail(str(exc))

    names = set()
    by_name = {member.name: member for member in members}

    def normalize_link_target(member_name: str, target: str) -> str:
        if not target or "\\" in target:
            raise ValueError(f"link escapes archive root: {member_name!r}")
        if target == NIX_STORE_PREFIX:
            resolved = f"{root}/nix/store"
        elif target.startswith(f"{NIX_STORE_PREFIX}/"):
            suffix = target[len(NIX_STORE_PREFIX) + 1 :]
            if not suffix or any(part in {"", ".", ".."} for part in suffix.split("/")):
                raise ValueError(f"link escapes archive root: {member_name!r}")
            resolved = f"{root}/nix/store/{suffix}"
        elif target.startswith("/"):
            raise ValueError(f"link escapes archive root: {member_name!r}")
        elif target == root or target.startswith(root + "/"):
            resolved = posixpath.normpath(target)
        else:
            resolved = posixpath.normpath(
                posixpath.join(posixpath.dirname(member_name), target)
            )
        if resolved != root and not resolved.startswith(root + "/"):
            raise ValueError(f"link escapes archive root: {member_name!r}")
        return resolved

    symlink_targets: dict[str, str] = {}
    hardlink_targets: dict[str, str] = {}
    for member in members:
        name = member.name
        if name in names:
            return fail(f"duplicate member {name!r}")
        names.add(name)
        if name.startswith("/") or "\\" in name:
            return fail(f"unsafe member path {name!r}")
        parts = name.split("/")
        if parts[0] != root or any(part in {"", ".", ".."} for part in parts[1:]):
            return fail(f"member escapes expected root: {name!r}")
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            return fail(f"unsupported member type: {name!r}")
        if name == root and not member.isdir():
            return fail("expected root is not a directory")
        if member.issym() or member.islnk():
            try:
                if member.issym():
                    symlink_targets[name] = member.linkname
                else:
                    hardlink_targets[name] = member.linkname
                normalize_link_target(name, member.linkname)
            except ValueError as exc:
                return fail(str(exc))

    def resolve_path(
        path: str,
        *,
        follow_final_symlink: bool,
        visited: set[str] | None = None,
    ) -> str:
        pending = path.split("/")
        resolved: list[str] = []
        visited = set() if visited is None else visited
        while pending:
            resolved.append(pending.pop(0))
            candidate = "/".join(resolved)
            if candidate not in symlink_targets or (
                not pending and not follow_final_symlink
            ):
                continue
            if candidate in visited:
                raise ValueError(f"cyclic symlink chain at {candidate!r}")
            visited.add(candidate)
            nested_path = normalize_link_target(candidate, symlink_targets[candidate])
            resolved = []
            pending = nested_path.split("/") + pending
        candidate = "/".join(resolved)
        if candidate not in by_name:
            raise ValueError(f"link target is absent: {path!r}")
        return candidate

    for name, target in symlink_targets.items():
        try:
            resolve_path(
                normalize_link_target(name, target),
                follow_final_symlink=True,
            )
        except ValueError as exc:
            return fail(str(exc))
    for name, target in hardlink_targets.items():
        try:
            resolved = resolve_path(
                normalize_link_target(name, target),
                follow_final_symlink=False,
            )
        except ValueError as exc:
            return fail(str(exc))
        if not by_name[resolved].isfile():
            return fail(f"hard-link target is not a regular file: {name!r}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: validate-kit-archive.py ARCHIVE EXPECTED_ROOT", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(validate(sys.argv[1], sys.argv[2]))
