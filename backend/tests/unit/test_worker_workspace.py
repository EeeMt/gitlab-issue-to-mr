import os
import time
from pathlib import Path
from types import SimpleNamespace

from app.core.worker_workspace import (
    build_issue_workspace_paths,
    cleanup_expired_workspaces,
    remove_issue_workspace,
)


def test_build_issue_workspace_paths():
    settings = SimpleNamespace(worker_workspace_host_path="/opt/codify-workspaces")
    issue = SimpleNamespace(id=456, project_id=123)
    task = SimpleNamespace(id=789)

    paths = build_issue_workspace_paths(settings, issue, task)

    assert paths.issue_root == "/opt/codify-workspaces/project-123/issue-456"
    assert paths.repo_path == "/opt/codify-workspaces/project-123/issue-456/repo"
    assert paths.claude_path == "/opt/codify-workspaces/project-123/issue-456/claude"
    assert paths.runtime_path == "/opt/codify-workspaces/project-123/issue-456/runtime/task-789"


def test_build_issue_workspace_paths_disabled_when_root_empty():
    settings = SimpleNamespace(worker_workspace_host_path="")
    issue = SimpleNamespace(id=456, project_id=123)
    task = SimpleNamespace(id=789)

    assert build_issue_workspace_paths(settings, issue, task) is None


def test_remove_issue_workspace_deletes_directory(tmp_path):
    issue_root = tmp_path / "project-1" / "issue-2"
    repo = issue_root / "repo"
    repo.mkdir(parents=True)
    (repo / "file.txt").write_text("data", encoding="utf-8")

    removed = remove_issue_workspace(str(issue_root))

    assert removed is True
    assert not issue_root.exists()


def test_remove_issue_workspace_returns_false_for_missing_path(tmp_path):
    assert remove_issue_workspace(str(tmp_path / "missing")) is False


def test_cleanup_expired_workspaces_removes_old_issue_dirs(tmp_path):
    old_issue = tmp_path / "project-1" / "issue-1"
    old_descendant = old_issue / "runtime" / "task-1" / "event.jsonl"
    old_descendant.parent.mkdir(parents=True)
    old_descendant.write_text("old", encoding="utf-8")
    old_mtime = time.time() - (40 * 24 * 60 * 60)
    os.utime(old_descendant, (old_mtime, old_mtime))
    os.utime(old_descendant.parent, (old_mtime, old_mtime))
    os.utime(old_descendant.parent.parent, (old_mtime, old_mtime))
    os.utime(old_issue, (old_mtime, old_mtime))

    removed = cleanup_expired_workspaces(str(tmp_path), retention_days=30)

    assert removed == 1
    assert not old_issue.exists()


def test_cleanup_expired_workspaces_keeps_issue_with_recent_descendant(tmp_path):
    old_issue = tmp_path / "project-1" / "issue-1"
    recent_descendant = old_issue / "claude" / "session.jsonl"
    recent_descendant.parent.mkdir(parents=True)
    recent_descendant.write_text("recent", encoding="utf-8")

    old_mtime = time.time() - (40 * 24 * 60 * 60)
    recent_mtime = time.time()
    os.utime(old_issue, (old_mtime, old_mtime))
    os.utime(recent_descendant, (recent_mtime, recent_mtime))

    removed = cleanup_expired_workspaces(str(tmp_path), retention_days=30)

    assert removed == 0
    assert old_issue.exists()


def test_cleanup_expired_workspaces_keeps_recent_issue_dirs(tmp_path):
    recent_issue = tmp_path / "project-1" / "issue-2"
    recent_issue.mkdir(parents=True)

    removed = cleanup_expired_workspaces(str(tmp_path), retention_days=30)

    assert removed == 0
    assert recent_issue.exists()
