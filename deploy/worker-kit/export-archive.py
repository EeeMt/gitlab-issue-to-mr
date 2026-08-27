#!/usr/bin/env python3
"""Rewrite a Docker Kit tar stream without materializing it on the host.

Docker exports a Linux Kit tree as a tar stream. Writing that stream directly
to the final archive preserves case-distinct paths such as ``P`` and ``p``
even when the caller runs on a case-insensitive host filesystem.
"""

from __future__ import annotations

import argparse
import copy
import posixpath
import sys
import tarfile
from pathlib import Path


def _safe_component(value: str, label: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


def _source_relative(name: str) -> str | None:
    while name.startswith("./"):
        name = name[2:]
    name = name.rstrip("/")
    if not name or name == ".":
        return None
    if name.startswith("/") or "\\" in name:
        raise ValueError(f"unsafe Docker Kit tar member: {name!r}")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe Docker Kit tar member: {name!r}")
    return posixpath.normpath(name)


def _hardlink_target(linkname: str, kit_name: str) -> str:
    if linkname == "/nix/store":
        return f"{kit_name}/nix/store"
    if linkname.startswith("/nix/store/"):
        suffix = linkname[len("/nix/store/") :]
        if not suffix or any(part in {"", ".", ".."} for part in suffix.split("/")):
            raise ValueError(f"unsafe Docker Kit hard-link target: {linkname!r}")
        return f"{kit_name}/nix/store/{suffix}"
    if linkname.startswith("/") or "\\" in linkname:
        raise ValueError(f"unsafe Docker Kit hard-link target: {linkname!r}")
    target = _source_relative(linkname)
    if target is None:
        raise ValueError(f"unsafe Docker Kit hard-link target: {linkname!r}")
    if target == kit_name or target.startswith(f"{kit_name}/"):
        return target
    return f"{kit_name}/{target}"


def export_archive(archive_path: Path, kit_name: str) -> None:
    kit_name = _safe_component(kit_name, "Kit archive root")
    seen: set[str] = set()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as source, tarfile.open(
            archive_path, mode="w:gz"
        ) as output:
            root = tarfile.TarInfo(kit_name)
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            output.addfile(root)
            for member in source:
                relative = _source_relative(member.name)
                if relative is None:
                    continue
                if relative in seen:
                    raise ValueError(f"duplicate Docker Kit tar member: {relative!r}")
                seen.add(relative)
                rewritten = copy.copy(member)
                rewritten.pax_headers = dict(member.pax_headers)
                rewritten.name = f"{kit_name}/{relative}"
                if member.islnk():
                    rewritten.linkname = _hardlink_target(member.linkname, kit_name)
                if "path" in rewritten.pax_headers:
                    rewritten.pax_headers["path"] = rewritten.name
                if "linkpath" in rewritten.pax_headers:
                    rewritten.pax_headers["linkpath"] = rewritten.linkname
                if member.isfile():
                    stream = source.extractfile(member)
                    if stream is None:
                        raise ValueError(f"Docker Kit tar member has no bytes: {member.name!r}")
                    try:
                        output.addfile(rewritten, stream)
                    finally:
                        stream.close()
                elif member.isdir() or member.issym() or member.islnk():
                    output.addfile(rewritten)
                else:
                    raise ValueError(f"unsupported Docker Kit tar member: {member.name!r}")
    except (OSError, tarfile.TarError, ValueError):
        archive_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("kit_name")
    args = parser.parse_args()
    try:
        export_archive(args.archive, args.kit_name)
    except (OSError, tarfile.TarError, ValueError) as exc:
        print(f"Worker Kit archive export failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
