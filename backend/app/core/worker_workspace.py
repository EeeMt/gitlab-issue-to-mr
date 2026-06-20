"""Helpers for persistent worker workspace paths and cleanup."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IssueWorkspacePaths:
    issue_root: str
    repo_path: str
    claude_path: str
    runtime_path: str
    shared_path: str


def build_issue_workspace_paths(settings: Any, issue: Any, task: Any) -> IssueWorkspacePaths | None:
    root = (getattr(settings, "worker_workspace_host_path", "") or "").strip()
    if not root:
        return None

    issue_root = os.path.join(
        root,
        f"project-{issue.project_id}",
        f"issue-{issue.id}",
    )
    return IssueWorkspacePaths(
        issue_root=issue_root,
        repo_path=os.path.join(issue_root, "repo"),
        claude_path=os.path.join(issue_root, "claude"),
        runtime_path=os.path.join(issue_root, "runtime", f"task-{task.id}"),
        shared_path=os.path.join(issue_root, "shared"),
    )


def remove_issue_workspace(issue_root: str) -> bool:
    if not issue_root or not os.path.exists(issue_root):
        return False
    shutil.rmtree(issue_root)
    return True


def _latest_tree_mtime(path: str) -> float:
    try:
        latest = os.path.getmtime(path)
    except OSError:
        latest = 0.0

    def _ignore_walk_error(_error: OSError) -> None:
        return None

    for dirpath, _dirnames, filenames in os.walk(path, onerror=_ignore_walk_error):
        try:
            latest = max(latest, os.path.getmtime(dirpath))
        except OSError:
            pass
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            try:
                latest = max(latest, os.path.getmtime(file_path))
            except OSError:
                pass

    return latest


def cleanup_expired_workspaces(root: str, *, retention_days: int) -> int:
    if not root or retention_days <= 0 or not os.path.isdir(root):
        return 0

    cutoff = time.time() - (retention_days * 24 * 60 * 60)
    candidates: list[str] = []

    # Issue workspaces use <root>/project-<id>/issue-<id>.
    # Restrict the scan to that layout so unrelated directories under the
    # configured root are never treated as disposable workspaces.
    for project_name in os.listdir(root):
        if not project_name.startswith("project-"):
            continue
        project_path = os.path.join(root, project_name)
        if not os.path.isdir(project_path):
            continue
        for issue_name in os.listdir(project_path):
            if not issue_name.startswith("issue-"):
                continue
            issue_path = os.path.join(project_path, issue_name)
            if os.path.isdir(issue_path):
                candidates.append(issue_path)

    # CI failure bundles share the workspace root and intentionally follow the
    # same retention period as issue workspaces.
    bundle_root = os.path.join(root, "ci-failures")
    if os.path.isdir(bundle_root):
        for run_name in os.listdir(bundle_root):
            bundle_path = os.path.join(bundle_root, run_name)
            if os.path.isdir(bundle_path):
                candidates.append(bundle_path)

    removed = 0
    for path in candidates:
        if _latest_tree_mtime(path) < cutoff:
            shutil.rmtree(path)
            removed += 1

    return removed
