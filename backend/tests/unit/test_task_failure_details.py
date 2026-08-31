import json
import tarfile

from app.core import task_failure_details
from app.core.worker import sanitize_sensitive_data


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


def test_sanitizes_openrouter_key_in_archived_upstream_detail(tmp_path, monkeypatch):
    secret = "sk-or-v1-abcdefghijklmnopqrstuvwxyz0123456789"
    _write_archive(tmp_path, [_session_error(raw=f"upstream key {secret}")])
    monkeypatch.setattr(task_failure_details, "_ARCHIVE_STORE", str(tmp_path))

    detail = task_failure_details.read_archived_harness_failure_detail(
        137,
        sanitize_sensitive_data,
    )

    assert detail is not None
    assert secret not in detail
    assert "[OPENROUTER_API_KEY]" in detail


def test_projects_legacy_pi_html_error_without_exposing_archive_payload(tmp_path, monkeypatch):
    _write_archive(
        tmp_path,
        [
            {
                "type": "message_end",
                "message": {
                    "errorMessage": "Not Found<!DOCTYPE html><script>secret payload</script>",
                },
            },
            {
                "type": "auto_retry_end",
                "finalError": "HTTP 404: <!DOCTYPE html><script>secret payload</script>",
            },
        ],
    )
    monkeypatch.setattr(task_failure_details, "_ARCHIVE_STORE", str(tmp_path))

    detail = task_failure_details.read_archived_harness_failure_detail(137, lambda text: text)

    assert detail == "Pi provider returned HTTP 404 HTML error response"
    assert len(detail) <= 1000
    assert "secret payload" not in detail
    assert "<" not in detail


def test_projects_legacy_pi_plain_error_with_a_bound(tmp_path, monkeypatch):
    _write_archive(
        tmp_path,
        [
            {
                "type": "auto_retry_end",
                "finalError": "Pi provider connection failed",
            }
        ],
    )
    monkeypatch.setattr(task_failure_details, "_ARCHIVE_STORE", str(tmp_path))

    detail = task_failure_details.read_archived_harness_failure_detail(137, lambda text: text)

    assert detail == "Pi provider connection failed"
