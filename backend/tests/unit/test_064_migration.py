"""Content-inspection tests for migration 064 (multi-harness runtime)."""

from __future__ import annotations

import re
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "064_multi_harness_runtime.py"
)


def test_migration_header_and_revision():
    content = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "064_multi_harness"' in content
    assert 'down_revision: Union[str, None] = "063_harness_runtime"' in content


def test_migration_adds_worker_profile_harness_fields():
    content = MIGRATION.read_text(encoding="utf-8")
    for column in (
        "enabled_harnesses",
        "default_harness_key",
        "harness_constraints",
        "image_digest",
        "harness_runtimes",
    ):
        assert re.search(rf'sa\.Column\(\s*"{column}"', content), column
    assert "'[\\\"claude\\\"]'" in content


def test_migration_adds_ai_provider_endpoint_fields():
    content = MIGRATION.read_text(encoding="utf-8")
    for column in (
        "provider_kind",
        "wire_protocol",
        "provider_driver",
        "provider_options",
        "credential_ref",
    ):
        assert re.search(rf'sa\.Column\(\s*"{column}"', content), column
    assert "'anthropic_compatible'" in content
    assert "'anthropic_messages'" in content


def test_migration_adds_snapshot_freeze_fields():
    content = MIGRATION.read_text(encoding="utf-8")
    for column in (
        "harness_key",
        "harness_adapter_version",
        "harness_adapter_digest",
        "harness_config_snapshot",
        "model_endpoint_snapshot",
        "credential_ref",
        "cli_source",
        "cli_executable_path",
        "cli_version",
        "cli_binary_digest",
        "image_digest",
        "runtime_contract_version",
        "orchestration_version",
        "runtime_bundle_digest",
    ):
        assert f'("{column}",' in content
    assert '"task_worker_profile_snapshots"' in content


def test_migration_creates_model_credentials_and_session_tables():
    content = MIGRATION.read_text(encoding="utf-8")
    assert 'op.create_table(\n        "model_credentials"' in content
    assert '"secret_encrypted"' in content
    assert "ix_model_credentials_ref" in content
    assert 'op.create_table(\n        "issue_harness_sessions"' in content
    assert "uq_issue_harness_session" in content
    assert "session_namespace" in content


def test_migration_backfills_harness_and_credentials():
    content = MIGRATION.read_text(encoding="utf-8")
    assert "SET harness_key = 'claude'" in content
    assert "model_credentials" in content
    assert "credential_ref = :ref" in content
    assert "legacy_backfill" in content
    assert "issue_harness_sessions" in content


def test_migration_downgrade_cleans_up():
    content = MIGRATION.read_text(encoding="utf-8")
    assert 'def downgrade() -> None:' in content
    assert 'op.drop_table("issue_harness_sessions")' in content
    assert 'op.drop_table("model_credentials")' in content
    assert 'op.drop_column("worker_profiles", name)' in content
    assert 'op.drop_column("ai_providers", name)' in content
    assert 'op.drop_column("task_worker_profile_snapshots", name)' in content
