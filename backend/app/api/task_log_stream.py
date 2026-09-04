"""Server-Sent Event generation for structured task logs."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from sqlalchemy import select

from app.models import Task, TaskLog, TaskStatus

TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}
BATCH_SIZE = 500
SLOW_QUERY_THRESHOLD_S = 0.5


def task_log_event_data(log: TaskLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "log_type": log.log_type,
        "metadata": json.loads(log.log_metadata) if log.log_metadata else None,
        "message": log.message,
        "created_at": log.created_at.isoformat(),
    }


async def generate_task_log_events(
    task_id: int,
    since_id: int,
    *,
    session_factory,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    logger: logging.Logger,
) -> AsyncIterator[str]:
    """Yield batched log and in-place update events without holding DB sessions."""
    cursor = since_id
    pending_tool_calls: set[int] = set()
    pending_thinking_rows: set[int] = set()
    stream_start = monotonic()
    total_events_sent = 0
    poll_cycle = 0
    first_batch_sent = False
    fast_forward_streak = 0
    fast_forward_logs = 0
    logger.info(
        f"[Task {task_id}] log-stream opened since_id={since_id} "
        f"resume={'yes' if since_id > 0 else 'no'}"
    )
    try:
        while True:
            poll_cycle += 1
            cycle_start = monotonic()
            cycle_log_data: list[dict[str, Any]] = []
            cycle_update_events: list[str] = []
            fast_forward = False
            current_status = None
            new_log_count = 0

            async with session_factory() as poll_db:
                query_start = monotonic()
                log_result = await poll_db.execute(
                    select(TaskLog)
                    .where(TaskLog.task_id == task_id, TaskLog.id > cursor)
                    .order_by(TaskLog.id.asc())
                    .limit(BATCH_SIZE)
                )
                new_logs = log_result.scalars().all()
                new_log_count = len(new_logs)
                query_ms = (monotonic() - query_start) * 1000

                if query_ms > SLOW_QUERY_THRESHOLD_S * 1000:
                    logger.warning(
                        f"[Task {task_id}] log-stream slow log query cycle={poll_cycle} "
                        f"cursor={cursor} fetched={new_log_count} query_ms={query_ms:.1f}"
                    )
                elif new_logs:
                    logger.debug(
                        f"[Task {task_id}] log-stream cycle={poll_cycle} "
                        f"fetched={new_log_count} cursor={cursor} query_ms={query_ms:.1f}"
                    )

                for log in new_logs:
                    event_data = task_log_event_data(log)
                    cursor = log.id
                    total_events_sent += 1
                    if log.log_type == "tool_call":
                        metadata = event_data["metadata"] or {}
                        if not metadata.get("output_payload_id"):
                            pending_tool_calls.add(log.id)
                    elif log.log_type == "thinking":
                        # Track placeholder rows so their final status reaches
                        # the page as an in-place update. Status decides the
                        # end (never payload_id): an empty thinking block also
                        # completes normally.
                        metadata = event_data["metadata"] or {}
                        if metadata.get("status") == "in_progress":
                            pending_thinking_rows.add(log.id)
                    cycle_log_data.append(event_data)

                if new_log_count == BATCH_SIZE:
                    fast_forward = True
                else:
                    if pending_tool_calls:
                        update_start = monotonic()
                        updated_result = await poll_db.execute(
                            select(TaskLog).where(TaskLog.id.in_(pending_tool_calls))
                        )
                        update_ms = (monotonic() - update_start) * 1000
                        if update_ms > SLOW_QUERY_THRESHOLD_S * 1000:
                            logger.warning(
                                f"[Task {task_id}] log-stream slow tool_call update query "
                                f"cycle={poll_cycle} pending={len(pending_tool_calls)} "
                                f"query_ms={update_ms:.1f}"
                            )
                        for log in updated_result.scalars().all():
                            metadata = json.loads(log.log_metadata) if log.log_metadata else {}
                            if metadata.get("output_payload_id"):
                                cycle_update_events.append(
                                    f"event: update\ndata: "
                                    f"{json.dumps(task_log_event_data(log))}\n\n"
                                )
                                pending_tool_calls.discard(log.id)
                                total_events_sent += 1

                    if pending_thinking_rows:
                        update_start = monotonic()
                        thinking_result = await poll_db.execute(
                            select(TaskLog).where(
                                TaskLog.task_id == task_id,
                                TaskLog.id.in_(pending_thinking_rows),
                            )
                        )
                        update_ms = (monotonic() - update_start) * 1000
                        if update_ms > SLOW_QUERY_THRESHOLD_S * 1000:
                            logger.warning(
                                f"[Task {task_id}] log-stream slow thinking update query "
                                f"cycle={poll_cycle} pending={len(pending_thinking_rows)} "
                                f"query_ms={update_ms:.1f}"
                            )
                        for log in thinking_result.scalars().all():
                            metadata = json.loads(log.log_metadata) if log.log_metadata else {}
                            # Finalize by status, never by payload_id: an empty
                            # thinking block still completes the placeholder.
                            if metadata.get("status") in ("completed", "interrupted"):
                                cycle_update_events.append(
                                    f"event: update\ndata: "
                                    f"{json.dumps(task_log_event_data(log))}\n\n"
                                )
                                pending_thinking_rows.discard(log.id)
                                total_events_sent += 1

                    status_start = monotonic()
                    task_result = await poll_db.execute(
                        select(Task.status).where(Task.id == task_id)
                    )
                    current_status = task_result.scalar_one_or_none()
                    status_ms = (monotonic() - status_start) * 1000
                    if status_ms > SLOW_QUERY_THRESHOLD_S * 1000:
                        logger.warning(
                            f"[Task {task_id}] log-stream slow status query cycle={poll_cycle} "
                            f"status={current_status} query_ms={status_ms:.1f}"
                        )

            cycle_ms = (monotonic() - cycle_start) * 1000
            if cycle_ms > 1000:
                logger.warning(
                    f"[Task {task_id}] log-stream slow cycle cycle={poll_cycle} "
                    f"cycle_ms={cycle_ms:.1f} total_sent={total_events_sent}"
                )

            if cycle_log_data:
                batch_payload = f"event: batch\ndata: {json.dumps(cycle_log_data)}\n\n"
                yield_started = monotonic()
                yield batch_payload
                yield_ms = (monotonic() - yield_started) * 1000
                if not first_batch_sent:
                    first_batch_sent = True
                    logger.info(
                        f"[Task {task_id}] log-stream first-batch "
                        f"cycle={poll_cycle} count={len(cycle_log_data)} "
                        f"time_to_first_ms={((yield_started - stream_start) * 1000):.1f} "
                        f"idle_cycles_before={poll_cycle - 1} yield_ms={yield_ms:.1f}"
                    )
                elif yield_ms > 500:
                    logger.warning(
                        f"[Task {task_id}] log-stream slow-yield "
                        f"cycle={poll_cycle} count={len(cycle_log_data)} "
                        f"yield_ms={yield_ms:.1f}"
                    )
            for event in cycle_update_events:
                yield event

            if len(pending_tool_calls) > 20 and poll_cycle % 10 == 1:
                logger.warning(
                    f"[Task {task_id}] log-stream large-pending-tool-calls "
                    f"size={len(pending_tool_calls)} cycle={poll_cycle}"
                )

            if fast_forward:
                fast_forward_streak += 1
                fast_forward_logs += len(cycle_log_data)
                continue

            if fast_forward_streak > 0:
                logger.info(
                    f"[Task {task_id}] log-stream fast-forward-done "
                    f"cycles={fast_forward_streak} logs={fast_forward_logs} cursor={cursor}"
                )
                fast_forward_streak = 0
                fast_forward_logs = 0

            if current_status not in TERMINAL_TASK_STATUSES and not new_log_count:
                if poll_cycle % 20 == 0:
                    logger.debug(
                        f"[Task {task_id}] log-stream alive "
                        f"cycle={poll_cycle} cursor={cursor} status={current_status} "
                        f"pending={len(pending_tool_calls)} "
                        f"elapsed_s={monotonic() - stream_start:.0f}"
                    )

            if current_status in TERMINAL_TASK_STATUSES and new_log_count == 0:
                yield "event: done\ndata: {}\n\n"
                elapsed_s = monotonic() - stream_start
                logger.info(
                    f"[Task {task_id}] log-stream closed reason=done "
                    f"total_events={total_events_sent} cycles={poll_cycle} "
                    f"elapsed_s={elapsed_s:.1f}"
                )
                break

            await sleep(1.5)

    except asyncio.CancelledError:
        elapsed_s = monotonic() - stream_start
        logger.info(
            f"[Task {task_id}] log-stream closed reason=client_disconnected "
            f"total_events={total_events_sent} cycles={poll_cycle} "
            f"elapsed_s={elapsed_s:.1f}"
            + (
                f" ff_streak_aborted={fast_forward_streak} ff_streak_logs={fast_forward_logs}"
                if fast_forward_streak > 0
                else ""
            )
        )
    except Exception as exc:
        elapsed_s = monotonic() - stream_start
        logger.error(
            f"[Task {task_id}] log-stream error after {elapsed_s:.1f}s "
            f"cycle={poll_cycle} total_events={total_events_sent}"
            + (f" ff_streak={fast_forward_streak}" if fast_forward_streak > 0 else "")
            + f": {exc}"
        )
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
