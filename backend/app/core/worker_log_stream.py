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
        t_start = time.monotonic()
        logger.info(
            f"[Task {task_id}] Log stream starting: timeout={timeout}s, "
            f"post_exit_drain={_POST_EXIT_DRAIN_SECONDS}s"
        )

        flush_interval = 10.0
        max_buffer_lines = 200

        loop = asyncio.get_running_loop()
        log_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)

        # Distinct sentinel objects so the main loop can tell the two threads apart.
        _STREAM_END = object()       # log stream exhausted  (from _stream_thread)
        _CONTAINER_EXITED = object() # container exited      (from _wait_thread)

        # Event set by _wait_thread when it completes (success or error).
        # Used in post-loop to wait for the exit code without needing a
        # duplicate container.wait() call that would race with _wait_thread.
        _wait_done = threading.Event()

        # Mutable cell: _wait_thread stores the container exit code here *before*
        # putting _CONTAINER_EXITED into the queue, so the main loop can read it
        # without a race.
        _container_exit_code: list[int] = []

        def _enqueue_chunk(chunk: bytes) -> None:
            try:
                log_queue.put_nowait(chunk)
            except asyncio.QueueFull:
                logger.warning(
                    f"[Task {task_id}] Log queue full (depth={log_queue.qsize()}), "
                    f"dropping chunk ({len(chunk)} bytes)"
                )

        def _stream_thread() -> None:
            logger.debug(f"[Task {task_id}] Stream thread started")
            try:
                for chunk in container.logs(stdout=True, stderr=True, follow=True, stream=True):
                    loop.call_soon_threadsafe(_enqueue_chunk, chunk)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[Task {task_id}] Log stream thread error: {exc}")
            finally:
                elapsed = time.monotonic() - t_start
                logger.info(f"[Task {task_id}] Stream thread exiting after {elapsed:.0f}s")
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
            t_wait_start = time.monotonic()
            logger.debug(f"[Task {task_id}] Wait thread started (timeout={timeout + 60}s)")
            try:
                result = container.wait(timeout=timeout + 60)
                code = result.get("StatusCode", -1) if isinstance(result, dict) else -1
                _container_exit_code.append(code)
                elapsed = time.monotonic() - t_wait_start
                logger.info(
                    f"[Task {task_id}] Wait thread: container exited with code={code} "
                    f"after {elapsed:.0f}s"
                )
            except Exception as exc:  # noqa: BLE001
                elapsed = time.monotonic() - t_wait_start
                logger.warning(
                    f"[Task {task_id}] Container exit-watcher thread error after {elapsed:.0f}s: {exc}"
                )
            finally:
                _wait_done.set()
                try:
                    loop.call_soon_threadsafe(log_queue.put_nowait, _CONTAINER_EXITED)
                except RuntimeError:
                    pass  # event loop already closed; nothing to do

        stream_thread = threading.Thread(target=_stream_thread, daemon=True)
        wait_thread = threading.Thread(target=_wait_thread, daemon=True)
        stream_thread.start()
        wait_thread.start()
        logger.info(
            f"[Task {task_id}] Both watcher threads started "
            f"(stream={stream_thread.name}, wait={wait_thread.name})"
        )

        buffer: list[str] = []
        all_lines: list[str] = []
        last_flush = time.monotonic()
        last_queue_log = t_start
        chunk_index = 0
        deadline = time.monotonic() + timeout
        container_exited = False
        bytes_received = 0
        chunks_received = 0

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                elapsed = time.monotonic() - t_start
                if buffer:
                    await self.flush_log_chunk(task_id, buffer, chunk_index)
                    chunk_index += 1
                stream_thread.join(timeout=2)
                wait_thread.join(timeout=2)
                if stream_thread.is_alive():
                    logger.warning(
                        f"[Task {task_id}] Timeout path: stream thread still alive after 2s join "
                        f"(likely blocked on dead TCP connection, elapsed={elapsed:.0f}s)"
                    )
                if container_exited and _container_exit_code:
                    # Container already exited but the log stream TCP connection is
                    # unresponsive (likely a silent NAT/firewall drop).  Return the
                    # real exit code so the task is marked correctly instead of
                    # being treated as a timeout.
                    logger.info(
                        f"[Task {task_id}] Log stream unresponsive {_POST_EXIT_DRAIN_SECONDS}s "
                        f"after container exit (exit_code={_container_exit_code[0]}); "
                        f"proceeding with actual exit code, total elapsed={elapsed:.0f}s"
                    )
                    return _container_exit_code[0], "".join(all_lines), chunk_index, False
                logger.warning(
                    f"[Task {task_id}] Log stream timed out after {timeout}s "
                    f"(elapsed={elapsed:.0f}s, chunks={chunks_received}, "
                    f"bytes={bytes_received}, container_exited={container_exited}, "
                    f"has_exit_code={bool(_container_exit_code)})"
                )
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
                elapsed = time.monotonic() - t_start
                logger.info(
                    f"[Task {task_id}] Log stream ended naturally after {elapsed:.0f}s, "
                    f"received {chunks_received} chunks ({bytes_received} bytes), "
                    f"queue depth at end={log_queue.qsize()}"
                )
                break

            if item is _CONTAINER_EXITED:
                # Container exited.  Shorten the deadline so a stuck stream
                # connection doesn't block for the full task_timeout.
                container_exited = True
                drain_deadline = time.monotonic() + _POST_EXIT_DRAIN_SECONDS
                if drain_deadline < deadline:
                    deadline = drain_deadline
                    logger.info(
                        f"[Task {task_id}] Container exited (exit_code={_container_exit_code[0] if _container_exit_code else '?'}); "
                        f"draining log stream for up to {_POST_EXIT_DRAIN_SECONDS}s"
                    )
                continue

            # Periodic queue depth health check
            now = time.monotonic()
            if (now - last_queue_log) >= 60:
                logger.info(
                    f"[Task {task_id}] Stream health: queue_depth={log_queue.qsize()}, "
                    f"chunks={chunks_received}, bytes={bytes_received}, "
                    f"elapsed={now - t_start:.0f}s, container_exited={container_exited}"
                )
                last_queue_log = now

            # Normal bytes chunk from the container log stream.
            chunks_received += 1
            bytes_received += len(item)
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
        if stream_thread.is_alive():
            logger.warning(
                f"[Task {task_id}] Stream thread did not exit within 5s join timeout "
                f"(thread may be blocked on a dead TCP connection)"
            )
        else:
            logger.debug(f"[Task {task_id}] Stream thread joined cleanly")

        # Wait for _wait_thread to signal completion via Event.
        # Using Event+_container_exit_code avoids the race / duplicate call
        # that a plain thread.join + fallback container.wait() would create.
        if _container_exit_code:
            # Wait thread already finished — nothing to wait for.
            exit_code = _container_exit_code[0]
        else:
            remaining_wait = max(deadline - time.monotonic(), 30)
            logger.info(
                f"[Task {task_id}] Log stream closed before container exit; "
                f"waiting up to {remaining_wait:.0f}s for wait thread"
            )
            t_wait = time.monotonic()
            await asyncio.to_thread(_wait_done.wait, remaining_wait)
            wait_elapsed = time.monotonic() - t_wait

            if _container_exit_code:
                exit_code = _container_exit_code[0]
                logger.info(
                    f"[Task {task_id}] Wait thread completed after {wait_elapsed:.0f}s "
                    f"with exit_code={exit_code}"
                )
            elif _wait_done.is_set():
                # _wait_thread finished but didn't capture an exit code (exception).
                # Fall back to a direct container.wait() — the container is already
                # exited so this should return quickly.  No race because _wait_thread
                # has already completed.
                t_fallback = time.monotonic()
                logger.info(
                    f"[Task {task_id}] Wait thread finished without exit code; "
                    f"trying fallback container.wait()"
                )
                try:
                    result = await asyncio.to_thread(container.wait, timeout=30)
                    exit_code = result.get("StatusCode", 1)
                    logger.info(
                        f"[Task {task_id}] Got exit_code={exit_code} from fallback "
                        f"container.wait() after {time.monotonic() - t_fallback:.0f}s"
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        f"[Task {task_id}] Fallback container.wait() error after "
                        f"{time.monotonic() - t_fallback:.0f}s: {exc}"
                    )
                    exit_code = -1
            else:
                # _wait_thread still running after remaining_wait — Docker daemon
                # is completely unresponsive.  Don't pile on another container.wait().
                logger.warning(
                    f"[Task {task_id}] Wait thread still unfinished after {wait_elapsed:.0f}s; "
                    f"Docker daemon may be unresponsive, giving up"
                )
                exit_code = -1

        elapsed = time.monotonic() - t_start
        logger.info(
            f"[Task {task_id}] Log stream complete: exit_code={exit_code}, "
            f"elapsed={elapsed:.0f}s, chunks={chunks_received}, bytes={bytes_received}"
        )
        return exit_code, "".join(all_lines), chunk_index, False
