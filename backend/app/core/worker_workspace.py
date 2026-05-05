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
    runtime_path: str


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
        runtime_path=os.path.join(issue_root, "runtime", f"task-{task.id}"),
    )


def remove_issue_workspace(issue_root: str) -> bool:
    if not issue_root or not os.path.exists(issue_root):
        return False
    shutil.rmtree(issue_root)
    return True


def cleanup_expired_workspaces(root: str, *, retention_days: int) -> int:
    if not root or retention_days <= 0 or not os.path.isdir(root):
        return 0

    cutoff = time.time() - (retention_days * 24 * 60 * 60)
    removed = 0

    for project_name in os.listdir(root):
        project_path = os.path.join(root, project_name)
        if not os.path.isdir(project_path):
            continue
        for issue_name in os.listdir(project_path):
            issue_path = os.path.join(project_path, issue_name)
            if not os.path.isdir(issue_path):
                continue
            if os.path.getmtime(issue_path) < cutoff:
                shutil.rmtree(issue_path)
                removed += 1

    return removed
