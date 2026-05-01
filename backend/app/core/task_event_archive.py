import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    event_jsonl: str
    runtime_json: str
    console_log: str


def artifact_paths(run_dir: str) -> ArtifactPaths:
    return ArtifactPaths(
        event_jsonl=os.path.join(run_dir, "event.jsonl"),
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
