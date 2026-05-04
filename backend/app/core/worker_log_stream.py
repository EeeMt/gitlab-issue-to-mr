"""Streaming helpers for worker container stdout/stderr ingestion."""

import asyncio
import logging
import threading
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskLog

logger = logging.getLogger(__name__)


class WorkerLogStreamer:
    """Streams container logs into TaskLog rows while parsing structured markers."""

    def __init__(self, *, scrub_sensitive_data, stdout_marker_parser) -> None:
        self._scrub_sensitive_data = scrub_sensitive_data
        self._stdout_marker_parser = stdout_marker_parser

    async def flush_log_chunk(
        self,
        task_id: int,
        lines: list[str],
        chunk_index: int,
        db: AsyncSession,
    ) -> None:
        content = self._scrub_sensitive_data("".join(lines)).strip()
        if not content:
            return
        if len(content) > 8000:
            content = content[:8000]
        db.add(TaskLog(task_id=task_id, log_level="INFO", message=content))
        await db.commit()
        logger.debug(f"[Task {task_id}] Saved log chunk {chunk_index} ({len(lines)} lines)")

    async def stream_logs_to_db(
        self,
        container: Any,
        task_id: int,
        db: AsyncSession,
        timeout: int,
    ) -> tuple[int, str, int, bool]:
        flush_interval = 10.0
        max_buffer_lines = 200

        loop = asyncio.get_running_loop()
        log_queue: asyncio.Queue = asyncio.Queue()

        def _stream_thread() -> None:
            try:
                for chunk in container.logs(stdout=True, stderr=True, follow=True, stream=True):
                    loop.call_soon_threadsafe(log_queue.put_nowait, chunk)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[Task {task_id}] Log stream thread error: {exc}")
            finally:
                loop.call_soon_threadsafe(log_queue.put_nowait, None)

        stream_thread = threading.Thread(target=_stream_thread, daemon=True)
        stream_thread.start()

        buffer: list[str] = []
        all_lines: list[str] = []
        last_flush = time.monotonic()
        chunk_index = 0
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(f"[Task {task_id}] Log stream timed out after {timeout}s")
                if buffer:
                    await self.flush_log_chunk(task_id, buffer, chunk_index, db)
                    chunk_index += 1
                stream_thread.join(timeout=2)
                return -1, "".join(all_lines), chunk_index, True

            try:
                item = await asyncio.wait_for(log_queue.get(), timeout=min(remaining, 2.0))
            except asyncio.TimeoutError:
                now = time.monotonic()
                if buffer and (now - last_flush) >= flush_interval:
                    await self.flush_log_chunk(task_id, buffer, chunk_index, db)
                    chunk_index += 1
                    buffer = []
                    last_flush = now
                continue

            if item is None:
                break

            text = item.decode("utf-8", errors="replace")
            lines = text.splitlines(keepends=True)

            for line in lines:
                stripped = line.rstrip('\n\r')
                if not stripped:
                    buffer.append(line)
                    all_lines.append(line)
                    continue

                await self._stdout_marker_parser.handle_line(stripped=stripped, task_id=task_id, db=db)
                buffer.append(line)
                all_lines.append(line)

            now = time.monotonic()
            if len(buffer) >= max_buffer_lines or (now - last_flush) >= flush_interval:
                await self.flush_log_chunk(task_id, buffer, chunk_index, db)
                chunk_index += 1
                buffer = []
                last_flush = now

        if buffer:
            await self.flush_log_chunk(task_id, buffer, chunk_index, db)
            chunk_index += 1

        stream_thread.join(timeout=5)

        try:
            result = await asyncio.to_thread(container.wait, timeout=30)
            exit_code = result.get("StatusCode", 1)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[Task {task_id}] container.wait() error: {exc}")
            exit_code = -1

        return exit_code, "".join(all_lines), chunk_index, False
