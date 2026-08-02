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
