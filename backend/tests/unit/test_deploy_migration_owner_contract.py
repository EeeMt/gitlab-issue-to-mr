"""Static contracts for the one-shot migration owner Compose topology."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
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
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            connection.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (current_revision,))
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
    with sqlite3.connect(database) as connection:
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


def test_v2_release_lock_validator_and_remote_daemon_preflight(tmp_path: Path):
    script = REPO_ROOT / "deploy" / "scripts" / "preflight-v2-release.sh"
    validator = REPO_ROOT / "deploy" / "scripts" / "validate-worker-cli-artifact-lock.py"
    env = os.environ.copy()
    env.pop("CODIFY_WORKER_CLI_ARTIFACT_MANIFEST_HOST_PATH", None)
    env.pop("CODIFY_V2_RELEASE_WORKER_IMAGE", None)

    missing_result = subprocess.run([str(script)], env=env, capture_output=True, text=True, check=False)

    assert missing_result.returncode == 2
    assert "Docker-daemon-visible regular file" in missing_result.stderr

    missing_image_result = subprocess.run(
        [str(script)],
        env={
            **env,
            "CODIFY_WORKER_CLI_ARTIFACT_MANIFEST_HOST_PATH": "/daemon/release-lock.json",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_image_result.returncode == 2
    assert "CODIFY_V2_RELEASE_WORKER_IMAGE" in missing_image_result.stderr

    lock = tmp_path / "worker-cli-artifacts.json"
    lock.write_text(
        json.dumps(
            {
                "schema": "codify.worker.cli-artifacts/v1",
                "platform": "linux/amd64",
                "artifacts": {
                    key: {"version": "1.2.3", "sha256": "a" * 64}
                    for key in ("claude", "codex", "pi", "opencode")
                },
            }
        )
    )
    valid_result = subprocess.run(
        [sys.executable, str(validator), str(lock)], capture_output=True, text=True, check=False
    )
    assert valid_result.returncode == 0

    wrong_platform_result = subprocess.run(
        [
            sys.executable,
            str(validator),
            "--expected-platform",
            "linux/arm64",
            str(lock),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_platform_result.returncode == 2
    assert "does not match the selected Docker daemon image platform" in wrong_platform_result.stderr

    wrong_image_lock_result = subprocess.run(
        [
            sys.executable,
            str(validator),
            "--expected-sha256",
            "0" * 64,
            str(lock),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_image_lock_result.returncode == 2
    assert "do not match the selected Worker image" in wrong_image_lock_result.stderr

    writable_result = subprocess.run(
        [sys.executable, str(validator), "--require-readonly", str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert writable_result.returncode == 2
    assert "not mounted read-only" in writable_result.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    invocation = tmp_path / "docker-invocation.txt"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {invocation}\n"
        "if [ \"$1\" = \"image\" ]; then printf '%s\\n' linux/amd64; fi\n"
        f"if [ \"$1\" = \"run\" ]; then printf '%s  /etc/codify-worker-cli-artifacts.json\\n' '{__import__('hashlib').sha256(lock.read_bytes()).hexdigest()}'; fi\n"
    )
    fake_docker.chmod(0o755)
    daemon_env = {
        **env,
        "CODIFY_WORKER_CLI_ARTIFACT_MANIFEST_HOST_PATH": str(lock),
        "CODIFY_V2_RELEASE_WORKER_IMAGE": "codify-worker/reviewed@sha256:deadbeef",
        "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
    }
    daemon_result = subprocess.run(
        [str(script)], env=daemon_env, capture_output=True, text=True, check=False
    )

    assert daemon_result.returncode == 0
    command = invocation.read_text()
    assert "compose -f" in command
    assert "docker-compose.v2-release.yml run --rm --no-deps --entrypoint python3 backend" in command
    assert "docker-compose.v2-release.yml run --rm --no-deps --entrypoint python3 scheduler" in command
    assert "--require-readonly --expected-platform linux/amd64 --expected-sha256" in command
    assert "/run/codify/worker-cli-artifacts.json" in command


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
