"""Streaming helpers for worker container stdout/stderr ingestion."""

import asyncio
import logging
import threading
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# How long to drain the log stream after the container exits before giving up.
# A healthy Docker daemon closes the stream almost immediately after container
# exit; this budget is only consumed when the TCP connection is already dead
# (e.g. due to NAT timeout on a remote Docker host).
_POST_EXIT_DRAIN_SECONDS = 30


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
    ) -> None:
        logger.debug(f"[Task {task_id}] Log chunk {chunk_index}: {len(lines)} lines buffered")

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

        # Distinct sentinel objects so the main loop can tell the two threads apart.
        _STREAM_END = object()       # log stream exhausted  (from _stream_thread)
        _CONTAINER_EXITED = object() # container exited      (from _wait_thread)

        # Mutable cell: _wait_thread stores the container exit code here *before*
        # putting _CONTAINER_EXITED into the queue, so the main loop can read it
        # without a race.
        _container_exit_code: list[int] = []

        def _stream_thread() -> None:
            try:
                for chunk in container.logs(stdout=True, stderr=True, follow=True, stream=True):
                    loop.call_soon_threadsafe(log_queue.put_nowait, chunk)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[Task {task_id}] Log stream thread error: {exc}")
            finally:
                try:
                    loop.call_soon_threadsafe(log_queue.put_nowait, _STREAM_END)
                except RuntimeError:
                    pass  # event loop already closed during shutdown

        def _wait_thread() -> None:
            """Wait for container exit and signal the main loop.

            Runs in parallel with _stream_thread using a *separate* HTTP connection
            to the Docker daemon.  When the container exits, container.wait() returns
            and we enqueue _CONTAINER_EXITED so the main loop can tighten its deadline
            and avoid blocking on a dead TCP connection indefinitely.

            This is the primary fix for the "task stuck in executing state" bug:
            container.logs(follow=True) can hang when the long-lived streaming TCP
            connection is silently dropped by NAT/firewall on a remote Docker host.
            container.wait() uses a fresh connection each time and is unaffected.
            """
            try:
                result = container.wait(timeout=timeout + 60)
                code = result.get("StatusCode", -1) if isinstance(result, dict) else -1
                _container_exit_code.append(code)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[Task {task_id}] Container exit-watcher thread error: {exc}")
            finally:
                try:
                    loop.call_soon_threadsafe(log_queue.put_nowait, _CONTAINER_EXITED)
                except RuntimeError:
                    pass  # event loop already closed; nothing to do

        stream_thread = threading.Thread(target=_stream_thread, daemon=True)
        wait_thread = threading.Thread(target=_wait_thread, daemon=True)
        stream_thread.start()
        wait_thread.start()

        buffer: list[str] = []
        all_lines: list[str] = []
        last_flush = time.monotonic()
        chunk_index = 0
        deadline = time.monotonic() + timeout
        container_exited = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if buffer:
                    await self.flush_log_chunk(task_id, buffer, chunk_index)
                    chunk_index += 1
                stream_thread.join(timeout=2)
                if container_exited and _container_exit_code:
                    # Container already exited but the log stream TCP connection is
                    # unresponsive (likely a silent NAT/firewall drop).  Return the
                    # real exit code so the task is marked correctly instead of
                    # being treated as a timeout.
                    logger.info(
                        f"[Task {task_id}] Log stream unresponsive {_POST_EXIT_DRAIN_SECONDS}s "
                        f"after container exit (exit_code={_container_exit_code[0]}); "
                        "proceeding with actual exit code"
                    )
                    return _container_exit_code[0], "".join(all_lines), chunk_index, False
                logger.warning(f"[Task {task_id}] Log stream timed out after {timeout}s")
                return -1, "".join(all_lines), chunk_index, True

            try:
                item = await asyncio.wait_for(log_queue.get(), timeout=min(remaining, 2.0))
            except asyncio.TimeoutError:
                now = time.monotonic()
                if buffer and (now - last_flush) >= flush_interval:
                    await self.flush_log_chunk(task_id, buffer, chunk_index)
                    chunk_index += 1
                    buffer = []
                    last_flush = now
                continue

            if item is _STREAM_END:
                # Log stream closed naturally — we have all the output.
                break

            if item is _CONTAINER_EXITED:
                # Container exited.  Shorten the deadline so a stuck stream
                # connection doesn't block for the full task_timeout.
                container_exited = True
                drain_deadline = time.monotonic() + _POST_EXIT_DRAIN_SECONDS
                if drain_deadline < deadline:
                    deadline = drain_deadline
                continue

            # Normal bytes chunk from the container log stream.
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
                await self.flush_log_chunk(task_id, buffer, chunk_index)
                chunk_index += 1
                buffer = []
                last_flush = now

        if buffer:
            await self.flush_log_chunk(task_id, buffer, chunk_index)
            chunk_index += 1

        stream_thread.join(timeout=5)

        if not _container_exit_code:
            # Log stream closed before the container exited (e.g. Docker dropped
            # the connection while the container was still running — task 418 class
            # of bug).  Give the container the remaining task budget to finish
            # rather than a hard-coded 30 s fallback.
            remaining_wait = max(deadline - time.monotonic(), 30)
            logger.info(
                f"[Task {task_id}] Log stream closed before container exit; "
                f"waiting up to {remaining_wait:.0f}s for container to finish"
            )
            await asyncio.to_thread(wait_thread.join, remaining_wait)
        else:
            wait_thread.join(timeout=2)

        if _container_exit_code:
            exit_code = _container_exit_code[0]
        else:
            # Last resort: container never exited within budget.
            try:
                result = await asyncio.to_thread(container.wait, timeout=30)
                exit_code = result.get("StatusCode", 1)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[Task {task_id}] container.wait() error: {exc}")
                exit_code = -1

        return exit_code, "".join(all_lines), chunk_index, False
