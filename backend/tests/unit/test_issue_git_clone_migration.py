from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "060_issue_git_clone_options.py"
)


def test_issue_git_clone_migration_is_chained_and_reversible():
    content = MIGRATION.read_text()

    assert 'revision: str = "060_issue_git_clone_options"' in content
    assert 'down_revision: Union[str, None] = "059_provider_runtime_snapshot"' in content
    assert '"git_clone_depth"' in content
    assert '"git_clone_filter"' in content
    assert "ck_issues_git_clone_depth" in content
    assert "ck_issues_git_clone_filter" in content
    assert 'op.drop_column("issues", "git_clone_filter")' in content
    assert 'op.drop_column("issues", "git_clone_depth")' in content
