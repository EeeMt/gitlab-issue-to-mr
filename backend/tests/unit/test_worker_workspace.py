import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.worker_workspace import (
    build_issue_workspace_paths,
    cleanup_expired_ci_failure_bundles,
)


def test_build_issue_workspace_paths():
    settings = SimpleNamespace(worker_workspace_host_path="/opt/codify-workspaces")
    issue = SimpleNamespace(id=456, project_id=123)
    task = SimpleNamespace(id=789)

    paths = build_issue_workspace_paths(settings, issue, task)

    assert paths.issue_root == "/opt/codify-workspaces/project-123/issue-456"
    assert paths.repo_path == "/opt/codify-workspaces/project-123/issue-456/repo"
    assert paths.claude_path == "/opt/codify-workspaces/project-123/issue-456/claude"
    assert paths.shared_path == "/opt/codify-workspaces/project-123/issue-456/shared"
    assert paths.meta_path == "/opt/codify-workspaces/project-123/issue-456/meta"


def test_build_issue_workspace_paths_disabled_when_root_empty():
    settings = SimpleNamespace(worker_workspace_host_path="")
    issue = SimpleNamespace(id=456, project_id=123)
    task = SimpleNamespace(id=789)

    assert build_issue_workspace_paths(settings, issue, task) is None


def test_build_issue_workspace_paths_disabled_when_root_is_not_string():
    settings = SimpleNamespace(worker_workspace_host_path=MagicMock())
    issue = SimpleNamespace(id=456, project_id=123)
    task = SimpleNamespace(id=789)

    assert build_issue_workspace_paths(settings, issue, task) is None


def test_local_cleanup_does_not_scan_daemon_issue_workspaces(tmp_path):
    old_issue = tmp_path / "project-1" / "issue-1"
    old_descendant = old_issue / "repo" / "file.txt"
    old_descendant.parent.mkdir(parents=True)
    old_descendant.write_text("old", encoding="utf-8")
    old_mtime = time.time() - (40 * 24 * 60 * 60)
    os.utime(old_descendant, (old_mtime, old_mtime))
    os.utime(old_descendant.parent, (old_mtime, old_mtime))
    os.utime(old_descendant.parent.parent, (old_mtime, old_mtime))
    os.utime(old_issue, (old_mtime, old_mtime))

    removed = cleanup_expired_ci_failure_bundles(str(tmp_path), retention_days=30)

    assert removed == 0
    assert old_issue.exists()


def test_cleanup_expired_workspaces_removes_old_ci_failure_bundles(tmp_path):
    old_bundle = tmp_path / "ci-failures" / "123"
    old_bundle.mkdir(parents=True)
    old_mtime = time.time() - (40 * 24 * 60 * 60)
    os.utime(old_bundle, (old_mtime, old_mtime))

    removed = cleanup_expired_ci_failure_bundles(str(tmp_path), retention_days=30)

    assert removed == 1
    assert not old_bundle.exists()


def test_cleanup_expired_workspaces_ignores_unrelated_directories(tmp_path):
    unrelated = tmp_path / "cache" / "entry"
    unrelated.mkdir(parents=True)
    old_mtime = time.time() - (40 * 24 * 60 * 60)
    os.utime(unrelated, (old_mtime, old_mtime))

    removed = cleanup_expired_ci_failure_bundles(str(tmp_path), retention_days=30)

    assert removed == 0
    assert unrelated.exists()
