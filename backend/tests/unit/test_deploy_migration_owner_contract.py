"""Static contracts for the one-shot migration owner Compose topology."""

import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tarfile
from contextlib import closing
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _service(content: str, name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", content, re.MULTILINE | re.DOTALL
    )
    assert match, f"missing service {name}"
    return match.group(1)


@pytest.mark.parametrize(
    "path",
    [
        REPO_ROOT / "deploy" / "docker-compose.yml",
        REPO_ROOT / "deploy" / "offline-bundle" / "docker-compose.yml",
    ],
)
def test_long_running_services_disable_auto_migrate_and_define_one_shot_owner(path: Path):
    content = path.read_text()
    for service in ("backend", "scheduler"):
        section = _service(content, service)
        assert "AUTO_MIGRATE=false" in section
    migrate = _service(content, "migrate")
    assert 'profiles: ["maintenance"]' in migrate
    assert "AUTO_MIGRATE=false" in migrate
    if path.name == "docker-compose.yml" and path.parent.name == "deploy":
        assert 'command: ["/usr/local/bin/run-migration-owner"]' in migrate
        assert "${MIGRATION_TARGET:-}" in migrate
        assert ":?set MIGRATION_TARGET" not in migrate
    else:
        assert "- alembic" in migrate
        assert "- upgrade" in migrate
        assert "${MIGRATION_TARGET:?set MIGRATION_TARGET to the reviewed Alembic revision}" in migrate


@pytest.mark.parametrize("target", [None, "", "head", "bad target"])
def test_migration_owner_rejects_blank_default_or_unreviewed_target(target: str | None):
    script = REPO_ROOT / "deploy" / "scripts" / "run-migration-owner.sh"
    env = os.environ.copy()
    if target is None:
        env.pop("MIGRATION_TARGET", None)
    else:
        env["MIGRATION_TARGET"] = target

    result = subprocess.run([str(script)], env=env, capture_output=True, text=True, check=False)

    assert result.returncode == 2
    assert "reviewed, non-head Alembic revision" in result.stderr


def _migration_owner_environment(
    tmp_path: Path, current_revision: str | None, label: str
) -> dict[str, str]:
    database = tmp_path / f"migration-owner-{label}.db"
    if current_revision is not None:
        with closing(sqlite3.connect(database)) as connection:
            with connection:
                connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                connection.execute(
                    "INSERT INTO alembic_version (version_num) VALUES (?)", (current_revision,)
                )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-m\" ] && [ \"$2\" = \"alembic\" ]; then exit 0; fi\n"
        f"exec {sys.executable} \"$@\"\n"
    )
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database}"
    return env


def test_migration_owner_rejects_unknown_and_ancestor_revision(tmp_path: Path):
    script = REPO_ROOT / "deploy" / "scripts" / "run-migration-owner.sh"
    for target, current, expected in (
        ("base", "074_open_harness_v2", "concrete Alembic revision"),
        ("does_not_exist", "074_open_harness_v2", "concrete Alembic revision"),
        ("074_open_harness_v2", "075_pi_command_dispatch_journal", "must not be an ancestor"),
    ):
        result = subprocess.run(
            [str(script)],
            cwd=REPO_ROOT / "backend",
            env={
                **_migration_owner_environment(tmp_path, current, target),
                "MIGRATION_TARGET": target,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        assert expected in result.stderr


def test_migration_owner_allows_a_concrete_forward_revision(tmp_path: Path):
    script = REPO_ROOT / "deploy" / "scripts" / "run-migration-owner.sh"

    result = subprocess.run(
        [str(script)],
        cwd=REPO_ROOT / "backend",
        env={
            **_migration_owner_environment(tmp_path, "074_open_harness_v2", "forward"),
            "MIGRATION_TARGET": "075_pi_command_dispatch_journal",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0


def test_migration_owner_allows_an_initial_database(tmp_path: Path):
    script = REPO_ROOT / "deploy" / "scripts" / "run-migration-owner.sh"

    result = subprocess.run(
        [str(script)],
        cwd=REPO_ROOT / "backend",
        env={
            **_migration_owner_environment(tmp_path, None, "initial"),
            "MIGRATION_TARGET": "075_pi_command_dispatch_journal",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0


def test_migration_owner_allows_a_merge_target_for_multiple_current_heads(tmp_path: Path):
    root = tmp_path / "merge-graph"
    versions = root / "alembic" / "versions"
    versions.mkdir(parents=True)
    (root / "alembic.ini").write_text("[alembic]\nscript_location = alembic\n")
    for revision, down_revision in (
        ("base_rev", None),
        ("branch_a", "base_rev"),
        ("branch_b", "base_rev"),
        ("merge_rev", ("branch_a", "branch_b")),
    ):
        (versions / f"{revision}.py").write_text(
            f"revision = {revision!r}\n"
            f"down_revision = {down_revision!r}\n"
            "branch_labels = None\n"
            "depends_on = None\n"
        )
    database = root / "merge.db"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            connection.executemany(
                "INSERT INTO alembic_version (version_num) VALUES (?)",
                [("branch_a",), ("branch_b",)],
            )
    env = _migration_owner_environment(tmp_path, "074_open_harness_v2", "merge-bin")
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database}"
    env["MIGRATION_TARGET"] = "merge_rev"

    result = subprocess.run(
        [str(REPO_ROOT / "deploy" / "scripts" / "run-migration-owner.sh")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0


def _worker_kit_manifest() -> dict:
    return {
        "schema_version": 2,
        "manifest_kind": "codify.worker.kit-manifest/v1",
        "kit_version": "0.3.15",
        "platform": "linux/amd64",
        "runtime_bin": "/bin",
        "bash": "/bin/bash",
        "entrypoint": "/opt/codify-kit/entrypoint.sh",
        "runtime_compatibility": {
            "harness_contracts": ["codify.worker.harness/v2"],
            "event_schemas": ["codify.worker.event/v2"],
        },
        "harness_inventory": {
            key: {
                "availability": "present",
                "path": f"/opt/codify-kit/harness/{key}/bin/{key}",
                "version": "1.0.0",
                "sha256": "a" * 64,
                "size": 7,
            }
            for key in ("claude", "codex", "opencode", "pi")
        },
    }


def _content_addressed_kit_archive(tmp_path: Path, manifest: dict) -> tuple[Path, str]:
    """Create a valid content-addressed kit archive plus its .sha256 sidecar."""
    content = b"kit-content\n"
    launcher = b"#!/bin/sh\n"
    runtime_verifier = b"#!/bin/sh\n"
    runtime_manifest_validator = b"# runtime manifest validator\n"
    content_verifier = b"# Worker Kit content verifier\n"
    manifest = {
        **manifest,
        "harness_inventory": {
            key: dict(entry) for key, entry in manifest.get("harness_inventory", {}).items()
        },
    }
    files = {
        "content.txt": content,
        "launcher": launcher,
        "verify-runtime.sh": runtime_verifier,
        "validate-runtime-manifest.py": runtime_manifest_validator,
        "verify-kit-content.py": content_verifier,
    }
    content_inventory = [
        {
            "kind": "file",
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
        for relative, payload in sorted(files.items())
    ]
    for key, entry in manifest["harness_inventory"].items():
        if entry.get("availability") != "present":
            continue
        relative = entry["path"].removeprefix("/opt/codify-kit/")
        payload = f"{key}-payload\n".encode()
        files[relative] = payload
        entry["sha256"] = hashlib.sha256(payload).hexdigest()
        entry["size"] = len(payload)
        content_inventory.append(
            {
                "kind": "file",
                "path": relative,
                "sha256": entry["sha256"],
                "size": entry["size"],
            }
        )
    content_inventory.sort(key=lambda item: item["path"])
    manifest["content_inventory"] = content_inventory
    manifest["content_inventory_sha256"] = hashlib.sha256(
        json.dumps(content_inventory, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest_bytes = json.dumps(manifest).encode()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    kit_name = f"codify-worker-kit-0.3.15-linux-amd64-{manifest_sha256[:12]}"
    archive_root = kit_name.removeprefix("codify-worker-kit-")
    kit_dir = tmp_path / "kit-root" / archive_root
    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "nix" / "store").mkdir(parents=True)
    (kit_dir / "manifest.json").write_bytes(manifest_bytes)
    for relative, payload in files.items():
        target = kit_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        if relative in {"launcher", "verify-runtime.sh"}:
            target.chmod(0o755)
    archive = tmp_path / "kits" / f"{kit_name}.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as output:
        output.add(kit_dir, arcname=archive_root)
    (tmp_path / "kits" / f"{archive.name}.sha256").write_text(
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    )
    return archive, manifest_sha256


def _case_distinct_content_addressed_kit_archive(tmp_path: Path) -> tuple[Path, str]:
    """Create a Kit archive whose Linux paths cannot be materialized on macOS."""
    manifest = _worker_kit_manifest()
    files = {
        "content.txt": b"kit-content\n",
        "launcher": b"#!/bin/sh\n",
        "verify-runtime.sh": b"#!/bin/sh\n",
        "validate-runtime-manifest.py": b"# runtime manifest validator\n",
        "verify-kit-content.py": b"# Worker Kit content verifier\n",
        "nix/store/case/P/file": b"upper\n",
        "nix/store/case/p/file": b"lower\n",
    }
    for key, entry in manifest["harness_inventory"].items():
        relative = entry["path"].removeprefix("/opt/codify-kit/")
        files[relative] = f"{key}-payload\n".encode()
        entry["sha256"] = hashlib.sha256(files[relative]).hexdigest()
        entry["size"] = len(files[relative])
    content_inventory = [
        {
            "kind": "file",
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
        for relative, payload in sorted(files.items())
    ]
    manifest["content_inventory"] = content_inventory
    manifest["content_inventory_sha256"] = hashlib.sha256(
        json.dumps(content_inventory, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest_bytes = json.dumps(manifest).encode()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    archive_root = f"0.3.15-linux-amd64-{manifest_sha256[:12]}"
    archive = tmp_path / f"codify-worker-kit-{archive_root}.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as output:
        root_member = tarfile.TarInfo(archive_root)
        root_member.type = tarfile.DIRTYPE
        root_member.mode = 0o755
        output.addfile(root_member)
        directories = {
            "nix",
            "nix/store",
            "nix/store/case",
            "nix/store/case/P",
            "nix/store/case/p",
        }
        for relative in sorted(directories):
            directory_member = tarfile.TarInfo(f"{archive_root}/{relative}")
            directory_member.type = tarfile.DIRTYPE
            directory_member.mode = 0o755
            output.addfile(directory_member)
        for relative, payload in sorted(files.items()):
            member = tarfile.TarInfo(f"{archive_root}/{relative}")
            member.size = len(payload)
            member.mode = 0o755 if relative in {"launcher", "verify-runtime.sh"} else 0o644
            output.addfile(member, io.BytesIO(payload))
        manifest_member = tarfile.TarInfo(f"{archive_root}/manifest.json")
        manifest_member.size = len(manifest_bytes)
        manifest_member.mode = 0o644
        output.addfile(manifest_member, io.BytesIO(manifest_bytes))
    (tmp_path / f"{archive.name}.sha256").write_text(
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    )
    return archive, manifest_sha256


def test_v2_release_preflight_validates_kit_archive_and_worker_image(tmp_path: Path):
    script = REPO_ROOT / "deploy" / "scripts" / "preflight-v2-release.sh"
    env = os.environ.copy()
    env.pop("WORKER_KIT_ARCHIVE", None)
    env.pop("V2_RELEASE_WORKER_IMAGE", None)

    missing_result = subprocess.run([str(script)], env=env, capture_output=True, text=True, check=False)
    assert missing_result.returncode == 2
    assert "WORKER_KIT_ARCHIVE" in missing_result.stderr

    missing_image_result = subprocess.run(
        [str(script)],
        env={
            **env,
            "WORKER_KIT_ARCHIVE": "/daemon/codify-worker-kit-0.3.15-linux-amd64-0123456789ab.tar.gz",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_image_result.returncode == 2
    assert "V2_RELEASE_WORKER_IMAGE" in missing_image_result.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = image ] && [ \"$2\" = inspect ]; then\n"
        "  printf '%s\\n' \"$IMAGE_IDENTITY\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    fake_docker.chmod(0o755)
    daemon_env = {
        **env,
        "V2_RELEASE_WORKER_IMAGE": "codify-worker/reviewed@sha256:deadbeef",
        "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
        "IMAGE_IDENTITY": "sha256:" + "a" * 64 + " linux/amd64",
    }

    archive, manifest_sha256 = _content_addressed_kit_archive(tmp_path, _worker_kit_manifest())
    valid_result = subprocess.run(
        [str(script)],
        env={**daemon_env, "WORKER_KIT_ARCHIVE": str(archive)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert valid_result.returncode == 0, valid_result.stderr
    assert "V2 release preflight OK: 0.3.15 linux/amd64" in valid_result.stdout
    assert manifest_sha256 in valid_result.stdout

    missing_archive_result = subprocess.run(
        [str(script)],
        env={**daemon_env, "WORKER_KIT_ARCHIVE": str(tmp_path / "missing.tar.gz")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_archive_result.returncode == 2
    assert "Worker Kit archive not found" in missing_archive_result.stderr

    bad_manifest = _worker_kit_manifest()
    bad_manifest["harness_inventory"] = {"pi": bad_manifest["harness_inventory"]["pi"]}
    bad_archive, _ = _content_addressed_kit_archive(tmp_path, bad_manifest)
    bad_manifest_result = subprocess.run(
        [str(script)],
        env={**daemon_env, "WORKER_KIT_ARCHIVE": str(bad_archive)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad_manifest_result.returncode == 2
    assert "harness_inventory must contain exactly the four keys" in bad_manifest_result.stderr

    renamed = tmp_path / "kits" / "codify-worker-kit-0.3.15-linux-amd64-renamed.tar.gz"
    archive.rename(renamed)
    (tmp_path / "kits" / f"{renamed.name}.sha256").write_text(
        f"{hashlib.sha256(renamed.read_bytes()).hexdigest()}  {renamed.name}\n"
    )
    name_result = subprocess.run(
        [str(script)],
        env={**daemon_env, "WORKER_KIT_ARCHIVE": str(renamed)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert name_result.returncode == 2
    assert "archive name is not content-addressed" in name_result.stderr

    wrong_prefix = tmp_path / "kits" / f"codify-worker-kit-0.3.15-linux-amd64-{'0' * 12}.tar.gz"
    renamed.rename(wrong_prefix)
    (tmp_path / "kits" / f"{wrong_prefix.name}.sha256").write_text(
        f"{hashlib.sha256(wrong_prefix.read_bytes()).hexdigest()}  {wrong_prefix.name}\n"
    )
    prefix_result = subprocess.run(
        [str(script)],
        env={**daemon_env, "WORKER_KIT_ARCHIVE": str(wrong_prefix)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert prefix_result.returncode == 2
    assert "archive path/link validation failed" in prefix_result.stderr

    platform_archive, _ = _content_addressed_kit_archive(tmp_path / "platform", _worker_kit_manifest())
    platform_result = subprocess.run(
        [str(script)],
        env={
            **daemon_env,
            "WORKER_KIT_ARCHIVE": str(platform_archive),
            "IMAGE_IDENTITY": "sha256:" + "a" * 64 + " linux/arm64",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert platform_result.returncode == 2
    assert "does not match the selected Worker image platform" in platform_result.stderr


def test_v2_release_preflight_reads_case_distinct_archive_without_extracting(tmp_path: Path):
    script = REPO_ROOT / "deploy" / "scripts" / "preflight-v2-release.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = image ] && [ \"$2\" = inspect ]; then\n"
        "  printf '%s\\n' \"$IMAGE_IDENTITY\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    fake_docker.chmod(0o755)
    fake_tar = fake_bin / "tar"
    fake_tar.write_text("#!/bin/sh\nexit 99\n")
    fake_tar.chmod(0o755)
    archive, manifest_sha256 = _case_distinct_content_addressed_kit_archive(
        tmp_path / "case-distinct"
    )
    result = subprocess.run(
        [str(script)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "WORKER_KIT_ARCHIVE": str(archive),
            "V2_RELEASE_WORKER_IMAGE": "codify-worker/reviewed@sha256:deadbeef",
            "IMAGE_IDENTITY": "sha256:" + "a" * 64 + " linux/amd64",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert manifest_sha256 in result.stdout


def test_e2e_runs_migrate_once_before_backend_and_never_enables_service_auto_migrate():
    content = (REPO_ROOT / "deploy" / "docker-compose.e2e.yml").read_text()
    migrate = _service(content, "migrate")
    assert "- alembic" in migrate
    assert "- upgrade" in migrate
    assert "AUTO_MIGRATE=false" in migrate
    backend = _service(content, "backend")
    scheduler = _service(content, "scheduler")
    assert "AUTO_MIGRATE=false" in backend
    assert "AUTO_MIGRATE=false" in scheduler
    assert "service_completed_successfully" in backend
