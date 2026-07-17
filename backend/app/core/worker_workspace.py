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
    shared_path: str
    meta_path: str


def configured_workspace_root(settings: Any) -> str | None:
    raw_root = getattr(settings, "worker_workspace_host_path", "")
    if not isinstance(raw_root, str):
        return None
    root = raw_root.strip()
    return root or None


def build_issue_workspace_paths(settings: Any, issue: Any, task: Any) -> IssueWorkspacePaths | None:
    root = configured_workspace_root(settings)
    if root is None:
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
        shared_path=os.path.join(issue_root, "shared"),
        meta_path=os.path.join(issue_root, "meta"),
    )


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


def cleanup_expired_ci_failure_bundles(root: str, *, retention_days: int) -> int:
    if not root or retention_days <= 0 or not os.path.isdir(root):
        return 0

    cutoff = time.time() - (retention_days * 24 * 60 * 60)
    candidates: list[str] = []
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
