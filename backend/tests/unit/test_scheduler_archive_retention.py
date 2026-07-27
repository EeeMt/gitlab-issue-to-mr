from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import reset_runtime_config, set_runtime_config
from app.core.utcnow import utcnow
from app.scheduler import Scheduler


def _db_with_archives(archives):
    result = MagicMock()
    result.scalars.return_value.all.return_value = archives
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_runtime_archive_retention_deletes_file_and_row(tmp_path):
    archive_path = tmp_path / "task-1-runtime-archive.tar.gz"
    archive_path.write_bytes(b"archive")
    archive = SimpleNamespace(
        id=1,
        archive_path=str(archive_path),
        created_at=utcnow() - timedelta(days=31),
    )
    db = _db_with_archives([archive])
    scheduler = Scheduler()
    scheduler._last_runtime_archive_cleanup_at = 0

    with patch(
        "app.scheduler.get_settings",
        return_value=SimpleNamespace(worker_runtime_archive_retention_days=30),
    ):
        await scheduler._maybe_cleanup_runtime_archives(db)

    assert not archive_path.exists()
    db.delete.assert_awaited_once_with(archive)
    db.commit.assert_awaited_once()
    assert scheduler._last_runtime_archive_cleanup_at > 0


@pytest.mark.asyncio
async def test_runtime_archive_retention_keeps_row_when_file_delete_fails(tmp_path):
    archive = SimpleNamespace(
        id=2,
        archive_path=str(tmp_path / "archive.tar.gz"),
        created_at=utcnow() - timedelta(days=31),
    )
    db = _db_with_archives([archive])
    scheduler = Scheduler()
    scheduler._last_runtime_archive_cleanup_at = 0

    with (
        patch(
            "app.scheduler.get_settings",
            return_value=SimpleNamespace(worker_runtime_archive_retention_days=30),
        ),
        patch("app.scheduler.os.remove", side_effect=PermissionError("denied")),
    ):
        await scheduler._maybe_cleanup_runtime_archives(db)

    db.delete.assert_not_awaited()
    db.commit.assert_awaited_once()
    assert archive.cleanup_next_attempt_at > archive.created_at
    assert scheduler._last_runtime_archive_cleanup_at > 0


@pytest.mark.asyncio
async def test_runtime_archive_retention_uses_effective_runtime_override():
    fixed_now = utcnow()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    captured_cutoffs = []

    async def capture_query(statement):
        captured_cutoffs.extend(
            value
            for value in statement.compile().params.values()
            if hasattr(value, "tzinfo")
        )
        return result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=capture_query)
    scheduler = Scheduler()
    scheduler._last_runtime_archive_cleanup_at = 0
    set_runtime_config({"worker_runtime_archive_retention_days": 90})
    try:
        with patch("app.scheduler.utcnow", return_value=fixed_now):
            await scheduler._maybe_cleanup_runtime_archives(db)
    finally:
        reset_runtime_config()

    assert fixed_now - timedelta(days=90) in captured_cutoffs
    assert fixed_now in captured_cutoffs


@pytest.mark.asyncio
async def test_full_runtime_archive_cleanup_batch_remains_due(tmp_path):
    archives = []
    for archive_id in range(100):
        archive_path = tmp_path / f"task-{archive_id}-runtime-archive.tar.gz"
        archive_path.write_bytes(b"archive")
        archives.append(
            SimpleNamespace(
                id=archive_id,
                archive_path=str(archive_path),
                created_at=utcnow() - timedelta(days=31),
            )
        )
    db = _db_with_archives(archives)
    scheduler = Scheduler()
    scheduler._last_runtime_archive_cleanup_at = 0

    with patch(
        "app.scheduler.get_settings",
        return_value=SimpleNamespace(worker_runtime_archive_retention_days=30),
    ):
        await scheduler._maybe_cleanup_runtime_archives(db)

    assert db.delete.await_count == 100
    db.commit.assert_awaited_once()
    assert scheduler._last_runtime_archive_cleanup_at == 0


@pytest.mark.asyncio
async def test_full_failed_runtime_archive_cleanup_batch_is_deferred_and_keeps_cleanup_due(
    tmp_path,
):
    archives = [
        SimpleNamespace(
            id=archive_id,
            archive_path=str(tmp_path / f"blocked-{archive_id}.tar.gz"),
            created_at=utcnow() - timedelta(days=31),
        )
        for archive_id in range(100)
    ]
    db = _db_with_archives(archives)
    scheduler = Scheduler()
    scheduler._last_runtime_archive_cleanup_at = 0
    fixed_now = utcnow()

    with (
        patch(
            "app.scheduler.get_settings",
            return_value=SimpleNamespace(worker_runtime_archive_retention_days=30),
        ),
        patch("app.scheduler.utcnow", return_value=fixed_now),
        patch("app.scheduler.os.remove", side_effect=PermissionError("denied")),
    ):
        await scheduler._maybe_cleanup_runtime_archives(db)

    db.delete.assert_not_awaited()
    db.commit.assert_awaited_once()
    assert {archive.cleanup_next_attempt_at for archive in archives} == {
        fixed_now + timedelta(hours=1)
    }
    assert scheduler._last_runtime_archive_cleanup_at == 0
