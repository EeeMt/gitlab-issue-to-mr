from app.core.task_event_archive import (
    archive_bundle_name,
    artifact_paths,
    decode_event_line,
    iter_complete_jsonl_records,
)


def test_artifact_paths_returns_expected_runtime_files():
    paths = artifact_paths("/tmp/task-run")

    assert paths.event_jsonl == "/tmp/task-run/event.jsonl"
    assert paths.harness_events_dir == "/tmp/task-run/harness-events"
    assert paths.harness_result_json == "/tmp/task-run/harness-result.json"
    assert paths.runtime_json == "/tmp/task-run/runtime.json"
    assert paths.console_log == "/tmp/task-run/console.log"


def test_decode_event_line_reads_jsonl_record():
    event = decode_event_line('{"type":"result","subtype":"success"}\n')

    assert event["type"] == "result"
    assert event["subtype"] == "success"


def test_archive_bundle_name_is_stable():
    assert archive_bundle_name(task_id=12) == "task-12-runtime-archive.tar.gz"


def test_iter_complete_jsonl_records_splits_partial_line():
    lines, remainder = iter_complete_jsonl_records('{"a":1}\n{"b":2}')
    assert lines == ['{"a":1}']
    assert remainder == '{"b":2}'


def test_iter_complete_jsonl_records_empty_buffer():
    lines, remainder = iter_complete_jsonl_records("")
    assert lines == []
    assert remainder == ""


def test_iter_complete_jsonl_records_all_complete():
    lines, remainder = iter_complete_jsonl_records('{"a":1}\n{"b":2}\n')
    assert lines == ['{"a":1}', '{"b":2}']
    assert remainder == ""
