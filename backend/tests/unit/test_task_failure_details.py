import json
import tarfile

from app.core import task_failure_details


def _write_archive(tmp_path, records: list[dict]) -> None:
    archive_path = tmp_path / "task-137-runtime-archive.tar.gz"
    payload = "".join(json.dumps(record) + "\n" for record in records).encode()
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("harness-events/opencode.jsonl")
        info.size = len(payload)
        archive.addfile(info, __import__("io").BytesIO(payload))


def _session_error(*, raw: str, status_code: int = 429) -> dict:
    return {
        "type": "session.error",
        "properties": {
            "sessionID": "session-not-displayed",
            "error": {
                "name": "APIError",
                "data": {
                    "message": "Provider returned error",
                    "statusCode": status_code,
                    "metadata": {
                        "url": "https://openrouter.ai/api/v1/messages?api_key=secret",
                    },
                    "responseBody": json.dumps({
                        "error": {"message": "generic upstream message"},
                        "metadata": {
                            "raw": raw,
                            "provider_name": "Decart",
                            "provider_error_code": "upstream_429",
                            "limit_source": "upstream_provider_shared_pool",
                            "retry_after_seconds": 5,
                        },
                        "request_id": "request-id-not-displayed",
                    }),
                    "responseHeaders": {"set-cookie": "secret-cookie"},
                },
            },
        },
    }


def test_reads_bounded_safe_detail_without_headers_or_request_id(tmp_path, monkeypatch):
    _write_archive(
        tmp_path,
        [_session_error(raw="z-ai/glm-5.2:free is temporarily rate-limited upstream")],
    )
    monkeypatch.setattr(task_failure_details, "_ARCHIVE_STORE", str(tmp_path))

    detail = task_failure_details.read_archived_harness_failure_detail(137, lambda text: text)

    assert detail == (
        "APIError: HTTP 429; z-ai/glm-5.2:free is temporarily rate-limited upstream; "
        "retry_after=5s; provider=Decart; provider_code=upstream_429; "
        "limit_source=upstream_provider_shared_pool; "
        "endpoint=https://openrouter.ai/api/v1/messages"
    )
    assert "set-cookie" not in detail
    assert "request-id-not-displayed" not in detail
    assert "api_key=secret" not in detail


def test_uses_latest_archived_session_error(tmp_path, monkeypatch):
    _write_archive(
        tmp_path,
        [
            _session_error(raw="first error", status_code=500),
            _session_error(raw="latest error", status_code=502),
        ],
    )
    monkeypatch.setattr(task_failure_details, "_ARCHIVE_STORE", str(tmp_path))

    detail = task_failure_details.read_archived_harness_failure_detail(137, lambda text: text)

    assert detail is not None
    assert "latest error" in detail
    assert "HTTP 502" in detail
