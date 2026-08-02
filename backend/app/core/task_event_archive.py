import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    event_jsonl: str
    harness_events_dir: str
    harness_result_json: str
    runtime_json: str
    console_log: str


def artifact_paths(run_dir: str) -> ArtifactPaths:
    return ArtifactPaths(
        event_jsonl=os.path.join(run_dir, "event.jsonl"),
        harness_events_dir=os.path.join(run_dir, "harness-events"),
        harness_result_json=os.path.join(run_dir, "harness-result.json"),
        runtime_json=os.path.join(run_dir, "runtime.json"),
        console_log=os.path.join(run_dir, "console.log"),
    )


def decode_event_line(line: str) -> dict[str, Any]:
    return json.loads(line)


def archive_bundle_name(*, task_id: int) -> str:
    return f"task-{task_id}-runtime-archive.tar.gz"


def iter_complete_jsonl_records(buffer: str) -> tuple[list[str], str]:
    lines = buffer.splitlines(keepends=True)
    complete = [line for line in lines if line.endswith("\n")]
    remainder = "" if not lines or lines[-1].endswith("\n") else lines[-1]
    return [line.rstrip("\n") for line in complete], remainder


from sqlalchemy import select as _sa_select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.models import TaskIngestCursor  # noqa: E402


async def get_or_create_cursor(
    db: AsyncSession,
    *,
    task_id: int,
    stream_name: str,
    attempt_id: str | None = None,
) -> TaskIngestCursor:
    """Get or create an ingest cursor for the given task and stream."""
    result = await db.execute(
        _sa_select(TaskIngestCursor)
        .where(
            TaskIngestCursor.task_id == task_id,
            TaskIngestCursor.stream_name == stream_name,
        )
        .with_for_update()
    )
    cursor = result.scalar_one_or_none()
    if cursor is None:
        cursor = TaskIngestCursor(
            task_id=task_id,
            stream_name=stream_name,
            attempt_id=attempt_id,
        )
        db.add(cursor)
        await db.flush()
    elif attempt_id is not None:
        if cursor.attempt_id is None and cursor.last_offset == 0 and cursor.last_sequence_no == 0:
            cursor.attempt_id = attempt_id
            await db.flush()
        elif cursor.attempt_id != attempt_id:
            raise ValueError(
                f"ingest cursor {task_id}/{stream_name} belongs to attempt "
                f"{cursor.attempt_id}, not {attempt_id}"
            )
    return cursor
