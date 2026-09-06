"""MR description rendering for the git_delivery contract (multi-commit).

Exercises worker_gitlab._build_mr_description directly with normalized
git_delivery metadata: this-task commit lists, recovered deliveries, net-diff
numbers, push outcome labels and Markdown/HTML escaping. Legacy single-SHA
tasks (no git_delivery) must keep the previous rendering.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.core import worker_gitlab
from app.models import Task, TaskStatus


def _task(task_id: int, *, status: TaskStatus = TaskStatus.COMPLETED) -> Task:
    now = datetime(2026, 7, 4, 10, 0, 0)
    task = Task(
        id=task_id,
        issue_id=7,
        project_id=3,
        user_prompt="Implement the contract",
        status=status,
        priority=1,
        is_retry=False,
        retry_source_task_id=None,
        trigger_source="manual",
        ci_failure_run_id=None,
        scheduled_at=None,
        container_id=None,
        commit_sha=None,
        error_message=None,
        additions=0,
        deletions=0,
        total_changes=0,
        input_tokens=None,
        output_tokens=None,
        model_name=None,
        commit_message=None,
        require_changes=False,
        task_mode="execute",
        session_mode="fresh",
        input_session_id=None,
        output_session_id=None,
        provider_id=None,
        worker_profile_id=None,
        created_at=now,
        updated_at=now,
        started_at=None,
        completed_at=None,
        is_manually_overridden=False,
        override_reason=None,
    )
    return task


def _issue():
    return SimpleNamespace(id=7, description=None)


def _git_delivery_meta(**overrides) -> dict:
    meta: dict = {
        "task_id": 1,
        "prompt": "Implement the contract",
        "execution_summary": "Executed.",
        "overall_summary": "",
        "commit_sha": "d" * 40,
        "commit_message": "latest subject",
        "additions": 10,
        "deletions": 4,
        "git_delivery": {
            "schema": "codify.git-delivery.v1",
            "attempt_id": "task-1-attempt-1",
            "branch": "codify/issue-7",
            "start_sha": "a" * 40,
            "start_remote_sha": "b" * 40,
            "head_sha": "d" * 40,
            "commits": [
                {"sha": "c" * 40, "subject": "harness made this"},
                {"sha": "d" * 40, "subject": "worker commit"},
            ],
            "recovered_commits": [{"sha": "b" * 40, "subject": "older pending work"}],
            "diff": {
                "additions": 10,
                "deletions": 4,
                "total": 14,
                "new_files": ["one.py"],
                "modified_files": ["two.py"],
                "deleted_files": [],
            },
            "push": {"status": "pushed", "remote_sha": "d" * 40, "error": None},
        },
    }
    meta.update(overrides)
    return meta


def _render(meta: dict, task: Task | None = None):
    task = task or _task(1)
    with patch.object(worker_gitlab, "get_settings") as mock_settings:
        mock_settings.return_value = SimpleNamespace(dashboard_url="http://codify.example.com")
        return worker_gitlab._build_mr_description(
            _issue(),
            [task],
            {1: meta},
        )


def test_multi_commit_delivery_renders_commits_recovery_and_stats():
    desc = _render(_git_delivery_meta())

    # This-task commits heading with both subjects.
    assert "本次提交（2）" in desc
    assert "harness made this" in desc
    assert "worker commit" in desc
    # Short SHA chips for each commit.
    assert f"`{('c' * 40)[:12]}`" in desc
    # Recovered delivery is separate, never merged into the commit count.
    assert "已有提交补交/确认（1）" in desc
    assert "older pending work" in desc
    # Net diff line.
    assert "**净变更**：+10 -4，新增 1 / 修改 1 / 删除 0 个文件" in desc
    # Push outcome.
    assert "**推送**：推送成功" in desc


def test_failed_push_is_marked_unconfirmed_with_human_reason():
    meta = _git_delivery_meta(
        task_id=1,
        commit_sha=None,
        commit_message=None,
        git_delivery={
            **_git_delivery_meta()["git_delivery"],
            "push": {
                "status": "failed",
                "remote_sha": None,
                "error": {
                    "code": "remote_diverged",
                    "message": "The remote task branch and the local head have diverged",
                },
            },
        },
    )
    desc = _render(meta, task=_task(1, status=TaskStatus.FAILED))

    # Table marks the failed delivery.
    assert "（交付未确认）" in desc
    # Details explain the reason in plain language.
    assert "**推送**：推送失败（交付未确认）" in desc
    assert "The remote task branch and the local head have diverged" in desc
    # No confirmed commit projection for an unconfirmed delivery.
    assert f"Commit: `{('d' * 40)[:12]}`" not in desc


def test_null_diff_stats_never_renders_as_zero():
    gd = _git_delivery_meta()["git_delivery"]
    gd["diff"] = {
        "additions": None,
        "deletions": None,
        "total": None,
        "new_files": [],
        "modified_files": [],
        "deleted_files": [],
    }
    desc = _render(_git_delivery_meta(git_delivery=gd))
    assert "+0 -0" not in desc
    assert "**净变更**" not in desc


def test_subjects_and_prompts_escape_markdown_html():
    gd = _git_delivery_meta()["git_delivery"]
    gd["commits"] = [
        {"sha": "d" * 40, "subject": "xss <script>alert(1)</script> | done </details>"}
    ]
    gd["push"] = {
        "status": "failed",
        "remote_sha": None,
        "error": {"code": "push_failed", "message": "boom <b>bold</b>"},
    }
    meta = _git_delivery_meta(git_delivery=gd, commit_sha=None, commit_message=None)
    desc = _render(meta, task=_task(1, status=TaskStatus.FAILED))

    assert "<script>" not in desc
    assert "&lt;script&gt;" in desc
    # Only the structural <details> closer may remain raw.
    assert desc.count("</details>") == 1
    assert "&lt;/details&gt;" in desc
    assert "<b>bold</b>" not in desc
    assert "boom &lt;b&gt;bold&lt;/b&gt;" in desc


def test_not_needed_delivery_shows_label_without_commit():
    gd = _git_delivery_meta()["git_delivery"]
    gd["commits"] = []
    gd["recovered_commits"] = []
    gd["push"] = {"status": "not_needed", "remote_sha": None, "error": None}
    desc = _render(_git_delivery_meta(git_delivery=gd, commit_sha=None, commit_message=None))
    assert "**推送**：无变更，无需推送" in desc
    assert "本次提交（0）" not in desc


def test_legacy_task_without_git_delivery_keeps_single_sha_rendering():
    task = _task(1)
    task.commit_sha = "e" * 40
    task.commit_message = "legacy single commit"
    meta = {"task_id": 1, "commit_sha": "e" * 40, "commit_message": "legacy single commit"}
    desc = _render(meta, task=task)

    assert f"Commit: `{('e' * 40)[:12]}`" in desc
    assert "legacy single commit" in desc
    assert "本次提交" not in desc
