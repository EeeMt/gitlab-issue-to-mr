from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "test-harness-migration.sh"


def _run(environment: dict[str, str]):
    return subprocess.run(
        [str(SCRIPT)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_migration_guard_requires_explicit_test_database_url():
    environment = dict(os.environ)
    environment.pop("CODIFY_MIGRATION_TEST_DATABASE_URL", None)
    environment.pop("DATABASE_URL", None)
    result = _run(environment)
    assert result.returncode == 2
    assert "is required" in result.stderr


def test_migration_guard_rejects_nonlocal_or_non_test_database():
    for url in (
        "postgresql+asyncpg://codify:codify@db.internal:5432/codify_test",
        "postgresql+asyncpg://codify:codify@127.0.0.1:5432/codify",
    ):
        environment = {
            **os.environ,
            "CODIFY_MIGRATION_TEST_DATABASE_URL": url,
        }
        environment.pop("DATABASE_URL", None)
        result = _run(environment)
        assert result.returncode == 2
        assert "explicit localhost" in result.stderr


def test_migration_guard_refuses_different_existing_database_url():
    result = _run(
        {
            **os.environ,
            "CODIFY_MIGRATION_TEST_DATABASE_URL": (
                "postgresql+asyncpg://codify:codify@127.0.0.1:55432/codify_test"
            ),
            "DATABASE_URL": "postgresql+asyncpg://codify:codify@127.0.0.1:5432/codify",
        }
    )
    assert result.returncode == 2
    assert "different DATABASE_URL" in result.stderr


def test_full_chain_does_not_consume_uncommitted_taskstatus_value():
    enum_migration = (
        REPO_ROOT / "backend" / "alembic" / "versions" / "002_queue_scheduling.py"
    ).read_text()
    migration = (
        REPO_ROOT / "backend" / "alembic" / "versions" / "048_task_raw_logs_finalized.py"
    ).read_text()

    assert 'op.execute("COMMIT")' in enum_migration
    assert "status::text IN ('completed', 'failed', 'cancelled')" in migration
