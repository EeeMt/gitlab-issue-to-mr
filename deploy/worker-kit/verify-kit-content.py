#!/usr/bin/env python3
"""Build and verify the canonical Worker Kit content inventory.

The manifest is the content-addressed identity record, so it cannot
list itself.  Generated installation metadata is excluded as well; every
other regular file and symlink under the Kit root is committed by path and
content digest in ``content_inventory``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import stat
import sys
import tarfile
from pathlib import Path


EXCLUDED_PATHS = frozenset({"manifest.json", ".install-receipt.json", ".smoke-passed"})
KIT_CONTAINER_PREFIX = "/opt/codify-kit/"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def inventory_digest(entries: list[dict]) -> str:
    return hashlib.sha256(_canonical_json(entries)).hexdigest()


def _relative_path(value: str) -> str:
    normalized = posixpath.normpath(value)
    if (
        not normalized
        or normalized in {".", ".."}
        or normalized.startswith("../")
        or normalized.startswith("/")
        or "\\" in value
        or any(part in {"", ".."} for part in normalized.split("/"))
        or normalized in EXCLUDED_PATHS
    ):
        raise ValueError(f"unsafe Kit content path: {value!r}")
    return normalized


def _file_entry(root: Path, path: Path, relative: str) -> dict:
    file_stat = path.lstat()
    if stat.S_ISREG(file_stat.st_mode):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "kind": "file",
            "path": relative,
            "sha256": digest.hexdigest(),
            "size": file_stat.st_size,
        }
    if stat.S_ISLNK(file_stat.st_mode):
        return {"kind": "symlink", "path": relative, "target": os.readlink(path)}
    raise ValueError(f"unsupported Worker Kit file type: {path.relative_to(root)}")


def _symlink_target_relative(relative: str, target: object) -> str:
    if not isinstance(target, str) or not target or target.startswith("/") or "\\" in target:
        raise ValueError(f"unsafe Worker Kit symlink target for {relative!r}")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))
    return _relative_path(resolved)


def _validate_directory_symlinks(root: Path, entries: list[dict]) -> None:
    for entry in entries:
        if entry["kind"] != "symlink":
            continue
        relative = entry["path"]
        _symlink_target_relative(relative, entry["target"])
        target = (root / relative).resolve(strict=True)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Worker Kit symlink escapes its root: {relative!r}") from exc


def _validate_archive_symlinks(entries: list[dict], member_paths: set[str]) -> None:
    for entry in entries:
        if entry["kind"] != "symlink":
            continue
        target = _symlink_target_relative(entry["path"], entry["target"])
        if target not in member_paths:
            raise ValueError(f"Worker Kit symlink target is absent: {entry['path']!r}")


def _manifest_relative_path(path: object) -> str:
    if not isinstance(path, str) or not path.startswith(KIT_CONTAINER_PREFIX):
        raise ValueError("Harness inventory path is not under /opt/codify-kit/")
    relative = path[len(KIT_CONTAINER_PREFIX) :]
    if (
        not relative
        or "\\" in relative
        or relative != posixpath.normpath(relative)
        or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise ValueError(f"unsafe Harness inventory path: {path!r}")
    return relative


def _validate_harness_content_paths(manifest: dict, entries: list[dict]) -> None:
    inventory = manifest.get("harness_inventory")
    if inventory is None:
        return
    if not isinstance(inventory, dict):
        raise ValueError("Worker Kit harness_inventory must be an object")
    by_path = {entry["path"]: entry for entry in entries}
    for key, value in inventory.items():
        if not isinstance(value, dict):
            raise ValueError(f"Worker Kit harness inventory entry is invalid: {key!r}")
        availability = value.get("availability")
        if availability == "present":
            relative = _manifest_relative_path(value.get("path"))
            content = by_path.get(relative)
            if content is None or content.get("kind") != "file":
                raise ValueError(
                    f"Worker Kit present Harness path is not a regular content file: {key!r}"
                )
        elif availability == "absent":
            prefix = f"harness/{key}/"
            if any(entry["path"].startswith(prefix) for entry in entries):
                raise ValueError(f"Worker Kit absent Harness ships content: {key!r}")
        else:
            raise ValueError(f"Worker Kit harness availability is invalid: {key!r}")


def directory_inventory(root: Path) -> list[dict]:
    """Return sorted content entries for all identity-bearing Kit files."""
    root = root.resolve()
    entries: list[dict] = []

    def visit(directory: Path, prefix: str = "") -> None:
        with os.scandir(directory) as scan:
            children = sorted(scan, key=lambda item: item.name)
        for child in children:
            relative = f"{prefix}/{child.name}" if prefix else child.name
            if relative in EXCLUDED_PATHS:
                continue
            child_path = Path(child.path)
            child_stat = child_path.lstat()
            if stat.S_ISDIR(child_stat.st_mode):
                visit(child_path, relative)
            else:
                entries.append(_file_entry(root, child_path, _relative_path(relative)))

    visit(root)
    _validate_directory_symlinks(root, entries)
    return sorted(entries, key=lambda item: item["path"])


def _archive_relative(name: str, root_name: str) -> str | None:
    root_name = root_name.rstrip("/")
    prefix = root_name + "/"
    if name.rstrip("/") == root_name:
        return None
    if not name.startswith(prefix):
        raise ValueError(f"archive member escapes Worker Kit root: {name!r}")
    relative = posixpath.normpath(name[len(prefix) :])
    if relative in EXCLUDED_PATHS:
        return relative
    return _relative_path(relative)


def _archive_link_target(relative: str, target: object, root_name: str) -> str:
    if not isinstance(target, str) or not target or target.startswith("/") or "\\" in target:
        raise ValueError(f"unsafe Worker Kit archive link target: {relative!r}")
    if target == root_name or target.startswith(f"{root_name}/"):
        candidate = target[len(root_name) :].lstrip("/")
    else:
        candidate = posixpath.join(posixpath.dirname(relative), target)
    return _relative_path(posixpath.normpath(candidate))


def archive_inventory(archive_path: Path, root_name: str) -> list[dict]:
    entries: list[dict] = []
    file_entries: dict[str, dict] = {}
    hardlink_targets: dict[str, str] = {}
    seen: set[str] = set()
    member_paths: set[str] = set()
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive:
            relative = _archive_relative(member.name, root_name)
            if relative is None or relative in EXCLUDED_PATHS:
                continue
            if relative in seen:
                    raise ValueError(f"duplicate Worker Kit content path: {relative!r}")
            seen.add(relative)
            member_paths.add(relative)
            if member.issym():
                entries.append({"kind": "symlink", "path": relative, "target": member.linkname})
                continue
            if member.islnk():
                target = _archive_link_target(relative, member.linkname, root_name)
                hardlink_targets[relative] = target
                continue
            if not member.isfile():
                if member.isdir():
                    continue
                raise ValueError(f"unsupported Worker Kit archive member: {member.name!r}")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"Worker Kit archive member has no bytes: {member.name!r}")
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
            entry = {
                "kind": "file",
                "path": relative,
                "sha256": digest.hexdigest(),
                "size": size,
            }
            entries.append(entry)
            file_entries[relative] = entry
    def resolve_hardlink(relative: str, visiting: set[str]) -> dict:
        target_entry = file_entries.get(relative)
        if target_entry is not None:
            return target_entry
        target = hardlink_targets.get(relative)
        if target is None or relative in visiting:
            raise ValueError(
                f"Worker Kit archive hard-link target is absent, cyclic, or not a file: {relative!r}"
            )
        target_entry = resolve_hardlink(target, visiting | {relative})
        entry = {
            "kind": "file",
            "path": relative,
            "sha256": target_entry["sha256"],
            "size": target_entry["size"],
        }
        file_entries[relative] = entry
        entries.append(entry)
        return entry

    for relative in hardlink_targets:
        resolve_hardlink(relative, set())
    _validate_archive_symlinks(entries, member_paths)
    return sorted(entries, key=lambda item: item["path"])


def _load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid Worker Kit manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Worker Kit manifest must be an object")
    return value


def _verify(expected: object, actual: list[dict], *, label: str) -> str:
    if expected != actual:
        raise ValueError(f"Worker Kit content inventory mismatch ({label})")
    return inventory_digest(actual)


def write_manifest(root: Path) -> str:
    manifest_path = root / "manifest.json"
    manifest = _load_manifest(manifest_path)
    entries = directory_inventory(root)
    _validate_harness_content_paths(manifest, entries)
    manifest["content_inventory"] = entries
    manifest["content_inventory_sha256"] = inventory_digest(entries)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest["content_inventory_sha256"]


def verify_directory(root: Path) -> str:
    manifest = _load_manifest(root / "manifest.json")
    entries = directory_inventory(root)
    digest = _verify(manifest.get("content_inventory"), entries, label="directory")
    _validate_harness_content_paths(manifest, entries)
    if manifest.get("content_inventory_sha256") != digest:
        raise ValueError("Worker Kit content inventory digest mismatch")
    return digest


def verify_archive(archive: Path, root_name: str) -> str:
    with tarfile.open(archive, "r:*") as bundle:
        manifest_member = next(
            (
                member
                for member in bundle.getmembers()
                if member.name == f"{root_name.rstrip('/')}/manifest.json"
            ),
            None,
        )
        if manifest_member is None:
            raise ValueError("Worker Kit archive contains no manifest.json")
        stream = bundle.extractfile(manifest_member)
        if stream is None:
            raise ValueError("Worker Kit manifest has no bytes")
        manifest = json.loads(stream.read().decode("utf-8"))
    entries = archive_inventory(archive, root_name)
    digest = _verify(manifest.get("content_inventory"), entries, label="archive")
    _validate_harness_content_paths(manifest, entries)
    if manifest.get("content_inventory_sha256") != digest:
        raise ValueError("Worker Kit content inventory digest mismatch")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--root-name")
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    try:
        if args.write_manifest:
            if args.root is None or args.archive is not None:
                raise ValueError("--write-manifest requires --root only")
            digest = write_manifest(args.root)
        elif args.root is not None and args.archive is None:
            digest = verify_directory(args.root)
        elif args.archive is not None and args.root_name:
            digest = verify_archive(args.archive, args.root_name)
        else:
            raise ValueError("use --root, --archive ARCHIVE --root-name NAME, or --write-manifest")
    except (OSError, ValueError, tarfile.TarError, UnicodeError) as exc:
        print(f"Worker Kit content verification failed: {exc}", file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
