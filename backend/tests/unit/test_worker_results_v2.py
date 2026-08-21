"""Tests for the V2 result-envelope validation wired into the result ingest path.

G1 closes the "neither-nor" gap: the backend must validate the frozen
``codify.worker.result/v2`` envelope (nested ``harness`` block) at ingest time,
so a flat/V1-shaped result masquerading as V2 is definitively rejected rather
than silently accepted.
"""

from __future__ import annotations

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
