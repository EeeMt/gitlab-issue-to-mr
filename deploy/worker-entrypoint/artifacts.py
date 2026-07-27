#!/usr/bin/env python3
"""Validate, seal, and archive task-local runtime artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

RUNTIME_DIR = Path("/tmp/codify-runtime")
ARTIFACT_DIR = RUNTIME_DIR / "artifacts"
POLICY_INPUT = RUNTIME_DIR / "artifact-policy.json"
POLICY_STATE = Path("/run/codify/artifact-policy.json")
VALIDATION_FILE = RUNTIME_DIR / "artifacts-validation.json"

DEFAULT_MAX_TOTAL_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 5_000
HARD_MAX_TOTAL_BYTES = 512 * 1024 * 1024
HARD_MAX_ENTRIES = 100_000
MAX_RUNTIME_ARCHIVE_BYTES = 640 * 1024 * 1024
MAX_RELATIVE_PATH_BYTES = 1_024
MAX_DEPTH = 32
MAX_METADATA_BYTES = 64 * 1024
MAX_POLICY_BYTES = 64 * 1024
COPY_CHUNK_BYTES = 1024 * 1024

BASE_ARCHIVE_FILES = (
    "event.jsonl",
    "runtime.json",
    "console.log",
    "delivery-summary.md",
    "delivery-summary-validation.json",
    "repository-preparation.json",
    "artifacts-validation.json",
)


class ArtifactError(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Policy:
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_entries: int = DEFAULT_MAX_ENTRIES
    warnings: tuple[str, ...] = ()


@dataclass
class Collection:
    file_count: int = 0
    directory_count: int = 0
    entry_count: int = 0
    total_bytes: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EntrySnapshot:
    device: int
    inode: int
    mode: int
    links: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> EntrySnapshot:
        return cls(
            device=value.st_dev,
            inode=value.st_ino,
            mode=value.st_mode,
            links=value.st_nlink,
            size=value.st_size,
            mtime_ns=value.st_mtime_ns,
            ctime_ns=value.st_ctime_ns,
        )


class LimitedWriter:
    def __init__(self, raw, limit: int) -> None:
        self.raw = raw
        self.limit = limit
        self.written = 0

    def write(self, content: bytes) -> int:
        if self.written + len(content) > self.limit:
            raise ArtifactError("archive_size_exceeded", "Runtime archive exceeds hard limit")
        written = self.raw.write(content)
        self.written += written
        return written

    def flush(self) -> None:
        self.raw.flush()

    def tell(self) -> int:
        return self.written


def _bounded_int(value: object, *, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < minimum or value > maximum:
        return None
    return value


def _read_trusted_root_json(path: Path) -> object:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & 0o022
            or info.st_size > MAX_POLICY_BYTES
        ):
            raise ValueError("untrusted artifact policy")
        with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as handle:
            return json.load(handle)
    finally:
        os.close(fd)


def _read_input_policy() -> Policy:
    warnings: list[str] = []
    try:
        try:
            payload = _read_trusted_root_json(POLICY_INPUT)
        except FileNotFoundError:
            return Policy(warnings=("system_policy_missing",))
        if not isinstance(payload, dict):
            raise ValueError("invalid artifact policy")
        total = _bounded_int(
            payload.get("max_total_bytes"), minimum=1024 * 1024, maximum=HARD_MAX_TOTAL_BYTES
        )
        single = _bounded_int(
            payload.get("max_file_bytes"), minimum=1024 * 1024, maximum=HARD_MAX_TOTAL_BYTES
        )
        entries = _bounded_int(
            payload.get("max_entries"), minimum=1, maximum=HARD_MAX_ENTRIES
        )
        if payload.get("schema_version") != 1 or None in (total, single, entries):
            raise ValueError("invalid artifact policy")
        assert total is not None and single is not None and entries is not None
        if single > total:
            raise ValueError("file limit exceeds total limit")
        return Policy(total, single, entries)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        warnings.append("system_policy_invalid")
        return Policy(warnings=tuple(warnings))
    finally:
        try:
            POLICY_INPUT.unlink(missing_ok=True)
        except OSError:
            pass


def _write_policy_state(policy: Policy) -> None:
    _secure_state_dir()
    fd, temp_name = tempfile.mkstemp(prefix=".artifact-policy-", dir=POLICY_STATE.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "schema_version": 1,
                    "max_total_bytes": policy.max_total_bytes,
                    "max_file_bytes": policy.max_file_bytes,
                    "max_entries": policy.max_entries,
                    "warnings": list(policy.warnings),
                },
                handle,
                separators=(",", ":"),
                sort_keys=True,
            )
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o600)
        os.replace(temp_path, POLICY_STATE)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _secure_state_dir() -> None:
    parent = POLICY_STATE.parent
    try:
        parent.mkdir(mode=0o700)
    except FileExistsError:
        pass
    state = parent.stat(follow_symlinks=False)
    if not stat.S_ISDIR(state.st_mode) or state.st_uid != 0 or state.st_mode & 0o022:
        raise RuntimeError("Artifact policy state directory is not root-owned and private")


def _trusted_runtime_root(value: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(value.st_mode)
        and value.st_uid == 0
        and not value.st_mode & 0o022
    )


def prepare(uid: int, gid: int) -> None:
    runtime_state = RUNTIME_DIR.stat(follow_symlinks=False)
    if not _trusted_runtime_root(runtime_state):
        raise RuntimeError("Task runtime root is not a trusted directory")
    policy = _read_input_policy()
    _write_policy_state(policy)
    try:
        ARTIFACT_DIR.mkdir(mode=0o700)
    except FileExistsError:
        pass
    artifact_state = ARTIFACT_DIR.stat(follow_symlinks=False)
    if not stat.S_ISDIR(artifact_state.st_mode):
        raise RuntimeError("Task artifact root is not a real directory")
    os.chown(ARTIFACT_DIR, uid, gid, follow_symlinks=False)
    ARTIFACT_DIR.chmod(0o700)
    if policy.warnings:
        print("WARNING: artifact policy fallback: " + ",".join(policy.warnings))


def _read_policy_state() -> Policy:
    try:
        payload = _read_trusted_root_json(POLICY_STATE)
        if not isinstance(payload, dict):
            raise ValueError("invalid policy state")
        total = _bounded_int(
            payload.get("max_total_bytes"), minimum=1024 * 1024, maximum=HARD_MAX_TOTAL_BYTES
        )
        single = _bounded_int(
            payload.get("max_file_bytes"), minimum=1024 * 1024, maximum=HARD_MAX_TOTAL_BYTES
        )
        entries = _bounded_int(
            payload.get("max_entries"), minimum=1, maximum=HARD_MAX_ENTRIES
        )
        if payload.get("schema_version") != 1 or None in (total, single, entries):
            raise ValueError("invalid policy state")
        assert total is not None and single is not None and entries is not None
        warnings = payload.get("warnings")
        safe_warnings = tuple(item for item in warnings or [] if isinstance(item, str))[:8]
        return Policy(total, min(single, total), entries, safe_warnings)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return Policy(warnings=("system_policy_state_invalid",))


_DECIMAL_RE = re.compile(r"^[0-9]{1,20}$")


def _profile_limit(name: str, system_value: int, maximum: int, warnings: list[str]) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return system_value
    if not _DECIMAL_RE.fullmatch(raw):
        warnings.append(f"{name.lower()}_invalid")
        return system_value
    value = int(raw)
    if value < 1 or value > maximum:
        warnings.append(f"{name.lower()}_invalid")
        return system_value
    return min(system_value, value)


def _effective_policy() -> Policy:
    system = _read_policy_state()
    warnings = list(system.warnings)
    total = _profile_limit(
        "CODIFY_ARTIFACT_MAX_TOTAL_BYTES",
        system.max_total_bytes,
        HARD_MAX_TOTAL_BYTES,
        warnings,
    )
    single = _profile_limit(
        "CODIFY_ARTIFACT_MAX_FILE_BYTES",
        system.max_file_bytes,
        HARD_MAX_TOTAL_BYTES,
        warnings,
    )
    entries = _profile_limit(
        "CODIFY_ARTIFACT_MAX_ENTRIES",
        system.max_entries,
        HARD_MAX_ENTRIES,
        warnings,
    )
    return Policy(total, min(single, total), entries, tuple(warnings[:16]))


def _decode_mount_path(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def _mounts() -> list[tuple[int, str]]:
    mounts: list[tuple[int, str]] = []
    with open("/proc/self/mountinfo", encoding="utf-8") as handle:
        for line in handle:
            fields = line.split()
            if len(fields) >= 5:
                mounts.append((int(fields[0]), _decode_mount_path(fields[4])))
    return mounts


def _mount_id(path: Path, mounts: list[tuple[int, str]]) -> int:
    resolved = os.path.abspath(path)
    matches = [
        (len(mount_path), mount_id)
        for mount_id, mount_path in mounts
        if resolved == mount_path or resolved.startswith(mount_path.rstrip("/") + "/")
    ]
    if not matches:
        raise ArtifactError("cross_mount", "Could not determine artifact mount")
    return max(matches)[1]


def _names(
    directory_fd: int,
    *,
    maximum: int,
    overflow_reason: str,
    overflow_message: str,
) -> list[str]:
    names: list[str] = []
    with os.scandir(directory_fd) as entries:
        for entry in entries:
            if len(names) >= maximum:
                raise ArtifactError(overflow_reason, overflow_message)
            names.append(entry.name)
    return sorted(names, key=os.fsencode)


def _same_entry(before: EntrySnapshot, after: os.stat_result) -> bool:
    return before == EntrySnapshot.from_stat(after)


def _check_relative_path(relative: Path, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise ArtifactError("depth_exceeded", "Artifact directory depth exceeds hard limit")
    raw = os.fsencode(str(relative))
    if len(raw) > MAX_RELATIVE_PATH_BYTES:
        raise ArtifactError("path_too_long", "Artifact relative path exceeds hard limit")
    if relative.is_absolute() or ".." in relative.parts:
        raise ArtifactError("invalid_path", "Artifact path escapes the fixed root")


def _copy_file(
    parent_fd: int,
    name: str,
    destination: Path,
    before: EntrySnapshot,
) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    file_fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        opened = os.fstat(file_fd)
        if not _same_entry(before, opened):
            raise ArtifactError("mutation_detected", "Artifact changed before copy")
        output_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IMODE(before.mode) & 0o777,
        )
        copied = 0
        try:
            while True:
                chunk = os.read(file_fd, COPY_CHUNK_BYTES)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > before.size:
                    raise ArtifactError("mutation_detected", "Artifact grew during copy")
                remaining = memoryview(chunk)
                while remaining:
                    written = os.write(output_fd, remaining)
                    if written <= 0:
                        raise ArtifactError("copy_failed", "Artifact copy made no progress")
                    remaining = remaining[written:]
        finally:
            os.close(output_fd)
        after = os.fstat(file_fd)
        if copied != before.size or not _same_entry(before, after):
            raise ArtifactError("mutation_detected", "Artifact changed during copy")
    finally:
        os.close(file_fd)


def _seal_directory(
    source_fd: int,
    source_path: Path,
    relative: Path,
    destination: Path,
    policy: Policy,
    collection: Collection,
    mounts: list[tuple[int, str]],
    root_mount_id: int,
    depth: int,
) -> None:
    directory_before = EntrySnapshot.from_stat(os.fstat(source_fd))
    names_before = _names(
        source_fd,
        maximum=policy.max_entries - collection.entry_count,
        overflow_reason="entry_limit_exceeded",
        overflow_message="Artifact entry limit exceeded",
    )
    for name in names_before:
        child_relative = relative / name
        child_path = source_path / name
        _check_relative_path(child_relative, depth)
        collection.entry_count += 1
        if collection.entry_count > policy.max_entries:
            raise ArtifactError("entry_limit_exceeded", "Artifact entry limit exceeded")
        if _mount_id(child_path, mounts) != root_mount_id:
            raise ArtifactError("cross_mount", "Artifact tree crosses a mount boundary")

        child_stat = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        before = EntrySnapshot.from_stat(child_stat)
        child_destination = destination / name
        if stat.S_ISDIR(child_stat.st_mode):
            collection.directory_count += 1
            child_destination.mkdir(mode=0o700)
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=source_fd,
            )
            try:
                if not _same_entry(before, os.fstat(child_fd)):
                    raise ArtifactError("mutation_detected", "Artifact directory was replaced")
                _seal_directory(
                    child_fd,
                    child_path,
                    child_relative,
                    child_destination,
                    policy,
                    collection,
                    mounts,
                    root_mount_id,
                    depth + 1,
                )
                if not _same_entry(before, os.fstat(child_fd)):
                    raise ArtifactError("mutation_detected", "Artifact directory changed")
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(child_stat.st_mode):
            if child_stat.st_nlink != 1:
                raise ArtifactError("invalid_entry", "Hard-linked artifact file is not allowed")
            if child_stat.st_size > policy.max_file_bytes:
                raise ArtifactError("file_size_exceeded", "Artifact file limit exceeded")
            if collection.total_bytes + child_stat.st_size > policy.max_total_bytes:
                raise ArtifactError("total_size_exceeded", "Artifact total limit exceeded")
            collection.file_count += 1
            collection.total_bytes += child_stat.st_size
            _copy_file(source_fd, name, child_destination, before)
        else:
            raise ArtifactError("invalid_entry", "Special artifact entry is not allowed")

    names_after = _names(
        source_fd,
        maximum=len(names_before),
        overflow_reason="mutation_detected",
        overflow_message="Artifact directory changed during sealing",
    )
    if names_before != names_after or not _same_entry(directory_before, os.fstat(source_fd)):
        raise ArtifactError("mutation_detected", "Artifact directory changed during sealing")


def _seal(policy: Policy) -> tuple[Path | None, Collection]:
    collection = Collection(warnings=list(policy.warnings))
    if not os.path.lexists(ARTIFACT_DIR):
        return None, collection

    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(ARTIFACT_DIR, flags)
    except OSError as exc:
        raise ArtifactError("invalid_root", "Artifact root is not a real directory") from exc

    staging = Path(tempfile.mkdtemp(prefix=".codify-artifacts-", dir="/tmp"))
    staging.chmod(0o700)
    try:
        mounts = _mounts()
        root_mount_id = _mount_id(ARTIFACT_DIR, mounts)
        _seal_directory(
            root_fd,
            ARTIFACT_DIR,
            Path(),
            staging,
            policy,
            collection,
            mounts,
            root_mount_id,
            1,
        )
        if collection.entry_count == 0:
            shutil.rmtree(staging)
            return None, collection
        return staging, collection
    except ArtifactError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise ArtifactError("mutation_detected", "Artifact changed during sealing") from exc
    finally:
        os.close(root_fd)


def _metadata(
    status: str,
    policy: Policy,
    collection: Collection,
    *,
    reason: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": status,
        "file_count": collection.file_count,
        "directory_count": collection.directory_count,
        "entry_count": collection.entry_count,
        "total_bytes": collection.total_bytes,
        "limits": {
            "max_total_bytes": policy.max_total_bytes,
            "max_file_bytes": policy.max_file_bytes,
            "max_entries": policy.max_entries,
        },
        "warnings": collection.warnings[:16],
    }
    if reason:
        payload["reason"] = reason
    return payload


def _write_metadata(payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    if len(encoded) > MAX_METADATA_BYTES:
        raise ArtifactError("metadata_size_exceeded", "Artifact validation metadata is too large")
    fd, temp_name = tempfile.mkstemp(prefix=".artifacts-validation-", dir=RUNTIME_DIR)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o644)
        os.replace(temp_path, VALIDATION_FILE)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _add_base_files(archive: tarfile.TarFile) -> None:
    for name in BASE_ARCHIVE_FILES:
        path = RUNTIME_DIR / name
        try:
            info = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISREG(info.st_mode):
            archive.add(path, arcname=name, recursive=False)


def _build_archive(archive_path: Path, sealed: Path | None) -> None:
    temp_path = archive_path.with_suffix(archive_path.suffix + ".part")
    temp_path.unlink(missing_ok=True)
    try:
        with open(temp_path, "xb") as raw:
            limited = LimitedWriter(raw, MAX_RUNTIME_ARCHIVE_BYTES)
            with tarfile.open(fileobj=limited, mode="w|gz") as archive:
                _add_base_files(archive)
                if sealed is not None:
                    archive.add(sealed, arcname="artifacts", recursive=True)
            limited.flush()
            os.fsync(raw.fileno())
        os.replace(temp_path, archive_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def create_archive(task_id: int) -> None:
    _lock_runtime_dir()
    policy = _effective_policy()
    archive_path = RUNTIME_DIR / f"task-{task_id}-runtime-archive.tar.gz"
    sealed: Path | None = None
    collection = Collection(warnings=list(policy.warnings))
    try:
        try:
            sealed, collection = _seal(policy)
            if sealed is None and collection.entry_count == 0:
                VALIDATION_FILE.unlink(missing_ok=True)
                _build_archive(archive_path, None)
                return
            _write_metadata(_metadata("included", policy, collection))
            try:
                _build_archive(archive_path, sealed)
                return
            except ArtifactError as exc:
                if exc.reason != "archive_size_exceeded":
                    raise
                _write_metadata(_metadata("omitted", policy, collection, reason=exc.reason))
                _build_archive(archive_path, None)
                return
        except ArtifactError as exc:
            _write_metadata(_metadata("omitted", policy, collection, reason=exc.reason))
            _build_archive(archive_path, None)
    finally:
        if sealed is not None:
            shutil.rmtree(sealed, ignore_errors=True)


def _lock_runtime_dir() -> None:
    runtime_state = RUNTIME_DIR.stat(follow_symlinks=False)
    if not stat.S_ISDIR(runtime_state.st_mode):
        raise ArtifactError("invalid_root", "Task runtime root is not a real directory")
    os.chown(RUNTIME_DIR, 0, 0, follow_symlinks=False)
    RUNTIME_DIR.chmod(0o755)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--uid", type=int, required=True)
    prepare_parser.add_argument("--gid", type=int, required=True)
    archive_parser = subparsers.add_parser("archive")
    archive_parser.add_argument("--task-id", type=int, required=True)
    args = parser.parse_args()

    if args.command == "prepare":
        prepare(args.uid, args.gid)
    else:
        create_archive(args.task_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
