"""Content-inspection tests for migration 068 (issue sequence + lineage)."""

from __future__ import annotations

import re
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "068_task_issue_sequence_and_lineage.py"
)


def test_migration_header_and_revision():
    content = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "068_task_issue_sequence_and_lineage"' in content
    assert 'down_revision: Union[str, None] = "067_harness_key"' in content


def test_migration_adds_nullable_task_columns():
    content = MIGRATION.read_text(encoding="utf-8")
    for col in (
        "issue_sequence",
        "projected_harness_key",
        "projected_session_namespace",
        "projected_lineage_generation",
        "projected_reset_task_id",
        "lineage_projection_reason",
        "input_lineage_reason",
    ):
        assert re.search(rf'op\.add_column\(\s*"tasks".*"{col}"', content, re.S)
        assert f'sa.Column("{col}"' in content


def test_migration_creates_session_lineage_table():
    content = MIGRATION.read_text(encoding="utf-8")
    assert "op.create_table(" in content
    assert '"issue_session_lineages"' in content
    assert "uq_issue_session_lineage_generation" in content
    assert "issue_id" in content
    assert "lineage_generation" in content
    assert "session_namespace" in content


def test_migration_backfills_sequence_via_row_number():
    content = MIGRATION.read_text(encoding="utf-8")
    assert "row_number() OVER" in content
    assert "ORDER BY created_at ASC, id ASC" in content
    assert "SET issue_sequence" in content


def test_migration_backfills_projected_lineage():
    content = MIGRATION.read_text(encoding="utf-8")
    assert "projected_lineage_generation" in content
    assert "lineage_projection_reason" in content
    assert "legacy_namespace_change" in content


def test_migration_creates_partial_unique_index():
    content = MIGRATION.read_text(encoding="utf-8")
    assert "uq_tasks_issue_sequence" in content
    assert "issue_sequence IS NOT NULL" in content


def test_migration_downgrade_drops_columns_and_table():
    content = MIGRATION.read_text(encoding="utf-8")
    assert 'op.drop_table("issue_session_lineages")' in content
    assert 'op.drop_column("tasks", "issue_sequence")' in content
