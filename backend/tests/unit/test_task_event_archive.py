from app.core.task_event_archive import (
    artifact_paths,
    decode_event_line,
    archive_bundle_name,
)


def test_artifact_paths_returns_expected_runtime_files():
    paths = artifact_paths("/tmp/task-run")

    assert paths.event_jsonl == "/tmp/task-run/event.jsonl"
    assert paths.runtime_json == "/tmp/task-run/runtime.json"
    assert paths.console_log == "/tmp/task-run/console.log"


def test_decode_event_line_reads_jsonl_record():
    event = decode_event_line('{"type":"result","subtype":"success"}\n')

    assert event["type"] == "result"
    assert event["subtype"] == "success"


def test_archive_bundle_name_is_stable():
    assert archive_bundle_name(task_id=12) == "task-12-runtime-archive.tar.gz"
