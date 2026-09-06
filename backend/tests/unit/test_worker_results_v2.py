"""Tests for the V2 result-envelope validation wired into the result ingest path.

G1 closes the "neither-nor" gap: the backend must validate the frozen
``codify.worker.result/v2`` envelope (nested ``harness`` block) at ingest time,
so a flat/V1-shaped result masquerading as V2 is definitively rejected rather
than silently accepted.
"""

from __future__ import annotations

import hashlib
import json
import tarfile

from app.core import worker_results


def _write_archive(tar_path, *, task_id: int, result: dict) -> None:
    with tarfile.open(tar_path, "w:gz") as archive:
        payload = json.dumps(result).encode("utf-8")
        info = tarfile.TarInfo("harness-result.json")
        info.size = len(payload)
        archive.addfile(info, __import__("io").BytesIO(payload))


def _v2_result(harness=None) -> dict:
    return {
        "schema": "codify.worker.result/v2",
        "status": "completed",
        "success": True,
        "result": {"text": "ok"},
        "harness": harness
        or {
            "key": "pi",
            "adapter_version": "2.0.0",
            "cli_version": "0.84.2",
            "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
            "model_protocols": ["anthropic_messages"],
        },
        "session_id": "s",
        "model": "m",
        "usage": {},
        "failure": None,
        "capability_warnings": [],
    }


def test_valid_v2_result_envelope_passes_ingest_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    archive = tmp_path / worker_results.archive_bundle_name(task_id=7)
    _write_archive(archive, task_id=7, result=_v2_result())

    assert worker_results._v2_result_validation_error(7) == ""


def test_flat_v2_result_envelope_is_rejected_at_ingest(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    archive = tmp_path / worker_results.archive_bundle_name(task_id=8)
    # A V1-flat shape carrying the V2 schema must be rejected: it is the exact
    # "neither-nor" state G1 eliminates (result validates as neither V1 nor V2).
    flat = _v2_result()
    flat["harness_key"] = "pi"
    flat["adapter_version"] = "2.0.0"
    flat["cli_version"] = "0.84.2"
    del flat["harness"]
    _write_archive(archive, task_id=8, result=flat)

    error = worker_results._v2_result_validation_error(8)
    assert error.startswith("protocol_error: V2 result envelope rejected")
    assert "harness" in error


def test_absent_archive_is_best_effort(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    # No archive written for task 9: best-effort, no error surfaced.
    assert worker_results._v2_result_validation_error(9) == ""


def _parse_task_result_db(task):
    """Async DB mock returning a run.completed terminal for the task."""
    from unittest.mock import AsyncMock, MagicMock

    db = MagicMock()
    order = [0]

    async def mock_execute(query, *a, **k):
        query_str = str(query)
        if "FROM task_logs" in query_str:
            result = MagicMock()
            order[0] += 1
            if order[0] == 1:
                entry = MagicMock()
                entry.log_metadata = '{"type":"run.completed","status":"completed","success":true}'
                result.scalar_one_or_none.return_value = entry
            else:
                result.scalar_one_or_none.return_value = None
            return result
        result = MagicMock()
        result.scalar_one_or_none.return_value = task
        return result

    db.execute = mock_execute
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def test_parse_task_result_fails_completed_run_on_invalid_v2_result(
    tmp_path, monkeypatch
):
    import asyncio

    from app.models import Task, TaskStatus

    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    task = Task(
        id=11,
        project_id=100,
        issue_id=1,
        user_prompt="p",
        status=TaskStatus.PENDING,
    )
    archive = tmp_path / worker_results.archive_bundle_name(task_id=11)
    flat = _v2_result()
    flat["harness_key"] = "pi"
    flat["adapter_version"] = "2.0.0"
    flat["cli_version"] = "0.84.2"
    del flat["harness"]
    _write_archive(archive, task_id=11, result=flat)

    db = _parse_task_result_db(task)
    from unittest.mock import MagicMock

    asyncio.run(
        worker_results.parse_task_result(
            task,
            logs="http://gitlab.example.com/project/-/merge_requests/1",
            db=db,
            exit_code=0,
            sanitize_sensitive_data=lambda s: s,
            gitlab_client=MagicMock(),
        )
    )

    assert task.status == TaskStatus.FAILED
    assert task.error_message.startswith("protocol_error: V2 result envelope rejected")


def test_parse_task_result_keeps_completed_on_valid_v2_result(tmp_path, monkeypatch):
    import asyncio

    from app.models import Task, TaskStatus

    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    task = Task(
        id=12,
        project_id=100,
        issue_id=1,
        user_prompt="p",
        status=TaskStatus.PENDING,
    )
    archive = tmp_path / worker_results.archive_bundle_name(task_id=12)
    _write_archive(archive, task_id=12, result=_v2_result())

    db = _parse_task_result_db(task)
    from unittest.mock import MagicMock

    asyncio.run(
        worker_results.parse_task_result(
            task,
            logs="http://gitlab.example.com/project/-/merge_requests/2",
            db=db,
            exit_code=0,
            sanitize_sensitive_data=lambda s: s,
            gitlab_client=MagicMock(),
        )
    )

    assert task.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# git_delivery projection contract (task git-delivery reconciliation design §7)
# ---------------------------------------------------------------------------


def _finalization_db(task, run_meta: dict, finalization_meta: dict):
    """Async DB mock returning per-log-type metadata in query order.

    parse_task_result loads run_result, harness_result, usage_final,
    system_init and worker_finalization in that order.
    """
    from unittest.mock import AsyncMock, MagicMock

    db = MagicMock()
    metas = [run_meta, {}, {}, {}, finalization_meta]
    order = [0]

    async def mock_execute(query, *a, **k):
        if "FROM task_logs" in str(query):
            result = MagicMock()
            index = order[0]
            order[0] += 1
            entry = MagicMock()
            payload = metas[index] if index < len(metas) else None
            entry.log_metadata = json.dumps(payload) if payload is not None else None
            result.scalar_one_or_none.return_value = entry if payload is not None else None
            return result
        result = MagicMock()
        result.scalar_one_or_none.return_value = task
        return result

    db.execute = mock_execute
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def _sha(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _gd_finalization(*, head_sha: str | None, push_status: str | None = "pushed", diff=None):
    commits = [{"sha": _sha("a"), "subject": "harness commit"}]
    git_delivery = {
        "schema": "codify.git-delivery.v1",
        "attempt_id": "task-99-attempt-1",
        "branch": "codify/issue-99",
        "start_sha": _sha("s"),
        "start_remote_sha": _sha("r"),
        "head_sha": head_sha,
        "commits": commits,
        "recovered_commits": [],
        "diff": diff
        or {"additions": 7, "deletions": 3, "total": 10, "new_files": ["a.py"], "modified_files": [], "deleted_files": []},
        "push": {"status": push_status, "remote_sha": head_sha, "error": None},
    }
    return {
        "exit_code": 0,
        "commit_sha": head_sha,
        "commit_message": "harness commit\n\nbody",
        "diff": {k: git_delivery["diff"][k] for k in ("additions", "deletions", "total")},
        "git_delivery": git_delivery,
    }


def _parse(task, finalization_meta, run_meta=None, exit_code: int = 0):
    import asyncio
    from unittest.mock import MagicMock

    run_meta = run_meta or {"type": "run.completed", "status": "completed", "success": True}
    db = _finalization_db(task, run_meta, finalization_meta)
    asyncio.run(
        worker_results.parse_task_result(
            task,
            logs="",
            db=db,
            exit_code=exit_code,
            sanitize_sensitive_data=lambda s: s,
            gitlab_client=MagicMock(),
        )
    )
    return task


def test_completed_run_projects_confirmed_git_delivery(tmp_path, monkeypatch):
    from app.models import Task, TaskStatus

    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    task = Task(id=99, project_id=100, issue_id=1, user_prompt="p", status=TaskStatus.PENDING)
    head = _sha("h")
    _parse(task, _gd_finalization(head_sha=head))

    assert task.status == TaskStatus.COMPLETED
    assert task.commit_sha == head
    assert task.commit_message == "harness commit\n\nbody"
    assert task.additions == 7
    assert task.deletions == 3
    assert task.total_changes == 10
    canonical = getattr(task, "_canonical_git_delivery", None)
    assert canonical is not None
    assert canonical["push"]["status"] == "pushed"
    assert canonical["diff"]["new_files"] == ["a.py"]
    assert canonical["commits"][0]["subject"] == "harness commit"


def test_completed_run_rejects_invalid_git_delivery_schema(tmp_path, monkeypatch):
    from app.models import Task, TaskStatus

    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    task = Task(id=99, project_id=100, issue_id=1, user_prompt="p", status=TaskStatus.PENDING)
    finalization = _gd_finalization(head_sha=_sha("h"))
    finalization["git_delivery"]["schema"] = "codify.git-delivery.v0"
    _parse(task, finalization)

    assert task.status == TaskStatus.FAILED
    assert "git_delivery rejected" in task.error_message
    assert getattr(task, "_canonical_git_delivery", None) is None


def test_completed_run_rejects_contradictory_commit_projection(tmp_path, monkeypatch):
    """Top-level commit_sha disagreeing with git_delivery.head_sha is invalid."""
    from app.models import Task, TaskStatus

    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    task = Task(id=99, project_id=100, issue_id=1, user_prompt="p", status=TaskStatus.PENDING)
    finalization = _gd_finalization(head_sha=_sha("h"))
    finalization["commit_sha"] = _sha("other")
    _parse(task, finalization)

    assert task.status == TaskStatus.FAILED
    assert "does not match" in task.error_message


def test_failed_run_stashes_collected_git_delivery_facts(tmp_path, monkeypatch):
    """Failure keeps local commit facts for display; unconfirmed -> no commit_sha."""
    from app.models import Task, TaskStatus

    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    task = Task(id=99, project_id=100, issue_id=1, user_prompt="p", status=TaskStatus.PENDING)
    finalization = _gd_finalization(head_sha=_sha("h"))
    finalization["exit_code"] = 1
    finalization["commit_sha"] = None  # push failed -> no confirmed projection
    finalization["commit_message"] = None
    finalization["git_delivery"]["push"] = {
        "status": "failed",
        "remote_sha": None,
        "error": {"code": "remote_diverged", "message": "remote diverged"},
    }
    run_meta = {
        "type": "run.failed",
        "status": "failed",
        "success": False,
        "failure": {"kind": "engine_error", "message": "delivery not confirmed"},
    }
    _parse(task, finalization, run_meta=run_meta, exit_code=1)

    assert task.status == TaskStatus.FAILED
    assert task.commit_sha is None
    assert "delivery not confirmed" in task.error_message
    canonical = getattr(task, "_canonical_git_delivery", None)
    assert canonical is not None
    assert canonical["commits"][0]["subject"] == "harness commit"
    assert canonical["push"]["error"]["code"] == "remote_diverged"


def test_null_diff_stats_are_never_zero_filled(tmp_path, monkeypatch):
    from app.models import Task, TaskStatus

    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    task = Task(id=99, project_id=100, issue_id=1, user_prompt="p", status=TaskStatus.PENDING)
    finalization = _gd_finalization(head_sha=_sha("h"))
    finalization["git_delivery"]["diff"] = {
        "additions": None,
        "deletions": None,
        "total": None,
        "new_files": ["a.py"],
        "modified_files": [],
        "deleted_files": [],
    }
    finalization["diff"] = None
    _parse(task, finalization)

    assert task.status == TaskStatus.COMPLETED
    assert task.commit_sha == _sha("h")
    # Uncollected statistics are never touched (no fabricated zero record).
    assert task.additions is None
    assert task.deletions is None
    assert task.change_stats_recorded_at is None


def test_recovered_only_confirmation_projects_head_sha(tmp_path, monkeypatch):
    """Recovered marker delivery (no new commits) still confirms the head."""
    from app.models import Task, TaskStatus

    monkeypatch.setattr(worker_results, "_ARCHIVE_STORE", str(tmp_path))
    task = Task(id=99, project_id=100, issue_id=1, user_prompt="p", status=TaskStatus.PENDING)
    head = _sha("h")
    finalization = _gd_finalization(head_sha=head)
    finalization["git_delivery"]["commits"] = []
    finalization["git_delivery"]["recovered_commits"] = [
        {"sha": head, "subject": "earlier delivery"}
    ]
    _parse(task, finalization)

    assert task.status == TaskStatus.COMPLETED
    assert task.commit_sha == head
    canonical = getattr(task, "_canonical_git_delivery", None)
    assert canonical["recovered_commits"][0]["subject"] == "earlier delivery"
