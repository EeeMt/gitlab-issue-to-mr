#!/usr/bin/env python3
"""Reject unsafe worker-kit tar members before any extraction."""

from __future__ import annotations

import posixpath
import sys
import tarfile


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

    def link_target(member: tarfile.TarInfo) -> str:
        target = member.linkname
        if target.startswith("/") or "\\" in target:
            raise ValueError(f"link escapes archive root: {member.name!r}")
        if target == root or target.startswith(root + "/"):
            resolved = posixpath.normpath(target)
        else:
            resolved = posixpath.normpath(
                posixpath.join(posixpath.dirname(member.name), target)
            )
        if resolved != root and not resolved.startswith(root + "/"):
            raise ValueError(f"link escapes archive root: {member.name!r}")
        if resolved not in by_name:
            raise ValueError(f"link target is absent: {member.name!r}")
        return resolved

    links: dict[str, str] = {}
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
                links[name] = link_target(member)
            except ValueError as exc:
                return fail(str(exc))

    visiting: set[str] = set()
    checked: set[str] = set()

    def check_link(name: str) -> bool:
        if name in checked:
            return True
        if name in visiting:
            return False
        visiting.add(name)
        target = links.get(name)
        if target is not None:
            target_member = by_name[target]
            if by_name[name].islnk() and not target_member.isfile():
                return False
            if target in links and not check_link(target):
                return False
        visiting.remove(name)
        checked.add(name)
        return True

    for name in links:
        if not check_link(name):
            return fail(f"cyclic or invalid link chain at {name!r}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: validate-kit-archive.py ARCHIVE EXPECTED_ROOT", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(validate(sys.argv[1], sys.argv[2]))
