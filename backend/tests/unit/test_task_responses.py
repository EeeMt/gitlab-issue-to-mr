"""Unit tests for Task API response helpers.

Covers ``apply_queue_context`` admin gating (§13.3/F4): the runtime locator
fingerprint is only merged into serialized Task payloads for platform admins;
non-admin and anonymous responses must not expose the daemon locator.
"""

from types import SimpleNamespace

from app.api.task_responses import apply_queue_context


def _ctx(runtime_fingerprint: str | None = "fp-admin-only") -> dict[int, dict]:
    return {
        1: {
            "queue_position": 1,
            "blocked_by_task_id": None,
            "waiting_reason": "worker_runtime_unavailable",
            "lock_owner_task_id": None,
            "waiting_since": None,
            "runtime_failure_code": "worker_kit_not_found",
            "runtime_failure_message": "kit missing",
            "runtime_checked_at": None,
            "runtime_locator_fingerprint": runtime_fingerprint,
        }
    }


def test_non_admin_response_strips_runtime_locator_fingerprint():
    data: dict = {}
    apply_queue_context(data, 1, _ctx(), current_user=SimpleNamespace(platform_role="member"))
    assert "runtime_locator_fingerprint" not in data
    # Other queue-context fields remain visible to non-admins.
    assert data["waiting_reason"] == "worker_runtime_unavailable"
    assert data["runtime_failure_code"] == "worker_kit_not_found"


def test_anonymous_response_strips_runtime_locator_fingerprint():
    data: dict = {}
    apply_queue_context(data, 1, _ctx(), current_user=None)
    assert "runtime_locator_fingerprint" not in data


def test_admin_response_includes_runtime_locator_fingerprint():
    data: dict = {}
    apply_queue_context(
        data,
        1,
        _ctx(),
        current_user=SimpleNamespace(platform_role="platform_admin"),
    )
    assert data["runtime_locator_fingerprint"] == "fp-admin-only"


def test_absent_context_does_not_leave_fingerprint_key_for_non_admin():
    data: dict = {}
    apply_queue_context(data, 1, {}, current_user=SimpleNamespace(platform_role="member"))
    assert "runtime_locator_fingerprint" not in data
    assert data["queue_position"] is None
