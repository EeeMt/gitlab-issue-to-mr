"""Final Worker artifact flush regression tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.worker_task_artifacts import flush_task_artifacts


@pytest.mark.asyncio
async def test_flush_uses_archive_when_stopped_container_rejects_final_exec():
    artifact_db = MagicMock()
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=artifact_db)
    session_context.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=session_context)
    worker = SimpleNamespace(
        _tail_event_jsonl=AsyncMock(side_effect=RuntimeError("409 container is not running")),
        _finalize_archive=AsyncMock(),
        _backfill_console_log_from_archive=AsyncMock(),
        _backfill_event_jsonl_from_archive=AsyncMock(),
    )
    task = SimpleNamespace(id=17)
    container = object()

    await flush_task_artifacts(
        worker,
        task=task,
        container=container,
        session_factory=session_factory,
    )

    worker._finalize_archive.assert_awaited_once_with(
        task_id=17,
        container=container,
        db=artifact_db,
    )
    worker._backfill_console_log_from_archive.assert_awaited_once_with(
        task_id=17,
        db=artifact_db,
    )
    worker._backfill_event_jsonl_from_archive.assert_awaited_once_with(
        task_id=17,
        db=artifact_db,
    )


# ---------------------------------------------------------------------------
# task-metadata.json persistence: canonical git_delivery merge (design §7.2.3)
# ---------------------------------------------------------------------------


def _metadata_worker(container_payload: dict):
    worker = SimpleNamespace(
        docker=SimpleNamespace(
            read_file_from_container=MagicMock(
                return_value=__import__("json").dumps(container_payload)
            )
        ),
    )
    return worker


def test_container_metadata_never_overwrites_canonical_git_delivery():
    """The canonical finalization object wins over the stale container copy."""
    import json

    from app.core.worker_task_artifacts import save_task_metadata_from_container

    stale_git_delivery = {
        "schema": "codify.git-delivery.v1",
        "attempt_id": "task-1-attempt-1",
        "branch": "codify/issue-1",
        "head_sha": "a" * 40,
        "commits": [{"sha": "a" * 40, "subject": "stale"}],
        "recovered_commits": [],
        "diff": {"additions": 1, "deletions": 0, "total": 1, "new_files": [], "modified_files": [], "deleted_files": []},
        "push": {"status": "failed", "remote_sha": None,
                 "error": {"code": "push_failed", "message": "stale failure"}},
    }
    canonical_git_delivery = {
        "schema": "codify.git-delivery.v1",
        "attempt_id": "task-1-attempt-1",
        "branch": "codify/issue-1",
        "head_sha": "b" * 40,
        "commits": [{"sha": "b" * 40, "subject": "confirmed"}],
        "recovered_commits": [],
        "diff": {"additions": 9, "deletions": 0, "total": 9, "new_files": [], "modified_files": [], "deleted_files": []},
        "push": {"status": "pushed", "remote_sha": "b" * 40, "error": None},
    }
    task = SimpleNamespace(
        id=1,
        _canonical_git_delivery=canonical_git_delivery,
        worker_metadata=None,
    )
    container_payload = {
        "task_id": 1,
        "commit_sha": None,
        "commit_message": None,
        "overall_summary": "fresh summary",
        "execution_summary": "…",
        "git_delivery": stale_git_delivery,
    }
    worker = _metadata_worker(container_payload)
    save_task_metadata_from_container(worker, container=object(), task=task, issue=None)

    assert task.worker_metadata["git_delivery"] == canonical_git_delivery
    assert task.worker_metadata["overall_summary"] == "fresh summary"
    assert json.dumps(container_payload["git_delivery"]) != json.dumps(
        task.worker_metadata["git_delivery"]
    )


def test_invalid_artifact_only_git_delivery_is_dropped():
    """No canonical parse (ingestion gap): unvalidated artifact objects never persist."""
    from app.core.worker_task_artifacts import save_task_metadata_from_container

    task = SimpleNamespace(id=1, _canonical_git_delivery=None, worker_metadata=None)
    container_payload = {
        "task_id": 1,
        "overall_summary": "s",
        "git_delivery": {"schema": "codify.git-delivery.v1", "head_sha": "short"},
    }
    save_task_metadata_from_container(
        _metadata_worker(container_payload), container=object(), task=task, issue=None
    )
    assert "git_delivery" not in task.worker_metadata
    assert task.worker_metadata["overall_summary"] == "s"


def test_absent_metadata_file_leaves_worker_metadata_untouched():
    from app.core.worker_task_artifacts import save_task_metadata_from_container

    worker = SimpleNamespace(
        docker=SimpleNamespace(read_file_from_container=MagicMock(return_value=None))
    )
    task = SimpleNamespace(id=1, _canonical_git_delivery=None, worker_metadata=None)
    save_task_metadata_from_container(worker, container=object(), task=task, issue=None)
    assert task.worker_metadata is None


def test_canonical_delivery_survives_missing_container_metadata(tmp_path):
    """F2: canonical git_delivery must not depend on task-metadata.json."""

    from app.core.worker_task_artifacts import save_task_metadata_from_container

    canonical = {
        "schema": "codify.git-delivery.v1",
        "attempt_id": "task-1-attempt-1-0123456789ab",
        "branch": "codify/issue-1",
        "start_sha": "a" * 40,
        "start_remote_sha": None,
        "head_sha": "b" * 40,
        "commits": [{"sha": "b" * 40, "subject": "confirmed"}],
        "recovered_commits": [],
        "diff": {"additions": 9, "deletions": 0, "total": 9, "new_files": [], "modified_files": [], "deleted_files": []},
        "push": {"status": "pushed", "remote_sha": "b" * 40, "error": None},
    }
    task = SimpleNamespace(id=1, _canonical_git_delivery=canonical, worker_metadata=None)
    # Container metadata file unreadable (None), like a removed/stale container.
    worker = SimpleNamespace(
        docker=SimpleNamespace(read_file_from_container=MagicMock(return_value=None))
    )
    save_task_metadata_from_container(worker, container=object(), task=task, issue=None)

    assert task.worker_metadata is not None
    assert task.worker_metadata["git_delivery"]["push"]["status"] == "pushed"
    assert task.worker_metadata["git_delivery"]["commits"][0]["sha"] == "b" * 40


def test_canonical_delivery_survives_invalid_container_metadata(tmp_path):
    from app.core.worker_task_artifacts import save_task_metadata_from_container

    canonical = {
        "schema": "codify.git-delivery.v1",
        "attempt_id": "task-1-attempt-1-0123456789ab",
        "branch": "codify/issue-1",
        "head_sha": "b" * 40,
        "commits": [{"sha": "b" * 40, "subject": "confirmed"}],
        "recovered_commits": [],
        "diff": {"additions": 1, "deletions": 0, "total": 1, "new_files": [], "modified_files": [], "deleted_files": []},
        "push": {"status": "pushed", "remote_sha": "b" * 40, "error": None},
    }
    task = SimpleNamespace(id=1, _canonical_git_delivery=canonical, worker_metadata=None)
    worker = SimpleNamespace(
        docker=SimpleNamespace(
            read_file_from_container=MagicMock(return_value="not json at all")
        )
    )
    save_task_metadata_from_container(worker, container=object(), task=task, issue=None)

    assert task.worker_metadata is not None
    assert task.worker_metadata["git_delivery"]["head_sha"] == "b" * 40
