#!/usr/bin/env python3
"""Unit tests for task archive and payload API endpoints."""
import os
import sys
import unittest
from datetime import datetime
from tempfile import NamedTemporaryFile
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-key")

from app.models import TaskPayload, TaskRunArchive


class TestGetTaskArchive(unittest.IsolatedAsyncioTestCase):
    async def test_get_task_archive_returns_metadata(self):
        """Test /tasks/{id}/archive returns archive metadata when it exists."""

        from app.api.tasks import get_task_archive

        mock_db = AsyncMock()
        mock_archive = TaskRunArchive(
            task_id=1,
            archive_name="task-1-runtime-archive.tar.gz",
            archive_path="/opt/codify-archives/task-1-runtime-archive.tar.gz",
            archive_size_bytes=1024,
            created_at=datetime(2025, 1, 1, 12, 0, 0),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_archive
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_access = MagicMock()
        result = await get_task_archive(task_id=1, db=mock_db, access_scope=mock_access)

        assert result["archive_name"] == "task-1-runtime-archive.tar.gz"
        assert result["archive_size_bytes"] == 1024
        assert result["file_exists"] is False

    async def test_get_task_archive_file_exists_when_file_present(self):
        """Test /tasks/{id}/archive returns file_exists=True when the file is on disk."""
        from app.api.tasks import get_task_archive

        with NamedTemporaryFile(suffix=".tar.gz") as tmp:
            tmp.write(b"archive")
            tmp.flush()
            mock_db = AsyncMock()
            mock_archive = TaskRunArchive(
                task_id=1,
                archive_name="task-1-runtime-archive.tar.gz",
                archive_path=tmp.name,
                archive_size_bytes=7,
                created_at=datetime(2025, 1, 1, 12, 0, 0),
            )
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_archive
            mock_db.execute = AsyncMock(return_value=mock_result)

            result = await get_task_archive(task_id=1, db=mock_db, access_scope=MagicMock())

            assert result["file_exists"] is True

    async def test_get_task_archive_404_when_no_archive(self):
        from fastapi import HTTPException

        from app.api.tasks import get_task_archive

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with self.assertRaises(HTTPException) as ctx:
            await get_task_archive(task_id=999, db=mock_db, access_scope=MagicMock())
        assert ctx.exception.status_code == 404

    async def test_download_task_archive_returns_file_response(self):
        from fastapi.responses import FileResponse

        from app.api.tasks import download_task_archive

        with NamedTemporaryFile(suffix=".tar.gz") as tmp:
            tmp.write(b"archive")
            tmp.flush()
            mock_db = AsyncMock()
            mock_archive = TaskRunArchive(
                task_id=1,
                archive_name="task-1-runtime-archive.tar.gz",
                archive_path=tmp.name,
                archive_size_bytes=7,
                created_at=datetime(2025, 1, 1, 12, 0, 0),
            )
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_archive
            mock_db.execute = AsyncMock(return_value=mock_result)

            result = await download_task_archive(task_id=1, db=mock_db, access_scope=MagicMock())

            assert isinstance(result, FileResponse)
            assert result.path == tmp.name
            assert result.filename == "task-1-runtime-archive.tar.gz"

    async def test_download_task_archive_404_when_file_missing(self):
        from fastapi import HTTPException

        from app.api.tasks import download_task_archive

        mock_db = AsyncMock()
        mock_archive = TaskRunArchive(
            task_id=1,
            archive_name="task-1-runtime-archive.tar.gz",
            archive_path="/tmp/not-present-runtime-archive.tar.gz",
            archive_size_bytes=7,
            created_at=datetime(2025, 1, 1, 12, 0, 0),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_archive
        mock_db.execute = AsyncMock(return_value=mock_result)

        with self.assertRaises(HTTPException) as ctx:
            await download_task_archive(task_id=1, db=mock_db, access_scope=MagicMock())
        assert ctx.exception.status_code == 404

    async def test_get_task_payload_returns_content(self):
        from app.api.tasks import get_task_payload

        mock_db = AsyncMock()
        mock_payload = TaskPayload(
            id=5,
            task_id=1,
            payload_kind="tool_input",
            encoding="identity",
            content=b'{"file_path": "a.py"}',
            char_count=21,
            byte_count=21,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_payload
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_task_payload(task_id=1, payload_id=5, db=mock_db, access_scope=MagicMock())

        assert result["content"] == '{"file_path": "a.py"}'
        assert result["payload_kind"] == "tool_input"

    async def test_get_task_payload_404_when_not_found(self):
        from fastapi import HTTPException

        from app.api.tasks import get_task_payload

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with self.assertRaises(HTTPException) as ctx:
            await get_task_payload(task_id=1, payload_id=999, db=mock_db, access_scope=MagicMock())
        assert ctx.exception.status_code == 404


if __name__ == "__main__":
    unittest.main()
