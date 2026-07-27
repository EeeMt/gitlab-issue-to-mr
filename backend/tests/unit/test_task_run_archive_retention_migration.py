from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "061_task_run_archive_retention.py"
)


def test_task_run_archive_retention_migration_is_chained_and_reversible():
    content = MIGRATION.read_text()

    assert 'revision: str = "061_task_run_archive_retention"' in content
    assert 'down_revision: Union[str, None] = "060_issue_git_clone_options"' in content
    assert '"cleanup_next_attempt_at"' in content
    assert '"ix_task_run_archives_created_id"' in content
    assert '["created_at", "id"]' in content
    assert 'op.drop_column("task_run_archives", "cleanup_next_attempt_at")' in content
