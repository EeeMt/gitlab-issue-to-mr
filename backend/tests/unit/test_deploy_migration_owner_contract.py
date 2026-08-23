"""Static contracts for the one-shot migration owner Compose topology."""

from __future__ import annotations

import re
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
    assert "- alembic" in migrate
    assert "- upgrade" in migrate
    assert "${MIGRATION_TARGET:?set MIGRATION_TARGET to the reviewed Alembic revision}" in migrate


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
