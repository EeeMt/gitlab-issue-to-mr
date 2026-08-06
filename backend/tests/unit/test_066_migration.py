"""Content-inspection tests for migration 066 (issue default harness)."""

from __future__ import annotations

import re
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "066_issue_default_harness_key.py"
)


def test_migration_header_and_revision():
    content = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "066_issue_default_harness_key"' in content
    assert 'down_revision: Union[str, None] = "065_worker_profile_verification"' in content


def test_migration_adds_issue_default_harness_and_backfills():
    content = MIGRATION.read_text(encoding="utf-8")
    assert re.search(
        r'sa\.Column\(\s*"default_harness_key"',
        content,
    )
    assert "UPDATE issues" in content
    assert "SET default_harness_key" in content
    assert "COALESCE(worker_profiles.default_harness_key, 'claude')" in content


def test_migration_downgrade_drops_column():
    content = MIGRATION.read_text(encoding="utf-8")
    assert 'op.drop_column("issues", "default_harness_key")' in content
