"""Unit tests for Kit-owned Harness availability gating (§11.3).

Covers the stable ``harness_cli_unavailable`` rejection on create/start/
retry/resume, the readiness-derived CLI resolution, and the fail-closed
identity checks that keep execution bound to the frozen
``image_identity + kit_identity + bundle_digest`` combination.
"""

from __future__ import annotations

import json

from app.core.worker_kit_inventory import (
    KIT_IDENTITY_SCHEMA,
    REASON_NOT_SELECTED,
)
from app.core.worker_runtime_readiness import (
    READINESS_READY,
    HarnessCliUnavailableError,
    RuntimeReadiness,
    harness_cli_unavailable_detail,
    is_harness_available,
)

_SHA = "a" * 64


def _readiness(
    *,
    inventory: dict | None = None,
    status: str = READINESS_READY,
    kit_version: str = "0.4.0",
) -> RuntimeReadiness:
    return RuntimeReadiness(
        status=status,
        worker_kit_version=kit_version,
        harness_inventory=inventory,
        kit_identity={
            "schema": KIT_IDENTITY_SCHEMA,
            "kit_version": kit_version,
            "platform": "linux/amd64",
            "manifest_sha256": _SHA,
        },
    )


def _inventory(present: set[str] | None = None) -> dict:
    present = present or {"pi"}
    inventory = {}
    for key in ("pi", "opencode", "claude", "codex"):
        if key in present:
            inventory[key] = {
                "availability": "present",
                "path": f"/opt/codify-kit/harness/{key}/bin/{key}",
                "version": "1.2.3",
                "sha256": _SHA,
                "size": 1234,
            }
        else:
            inventory[key] = {"availability": "absent", "reason_code": REASON_NOT_SELECTED}
    return inventory


def test_is_harness_available_requires_explicit_present_entry():
    readiness = _readiness(inventory=_inventory({"pi", "opencode"}))
    assert is_harness_available(readiness, "pi") is True
    assert is_harness_available(readiness, "opencode") is True
    assert is_harness_available(readiness, "claude") is False
    assert is_harness_available(readiness, "codex") is False


def test_is_harness_available_unknown_inventory_never_rejects():
    readiness = _readiness(inventory=None)
    assert is_harness_available(readiness, "pi") is None
    readiness = _readiness(inventory={})
    assert is_harness_available(readiness, "pi") is None


def test_is_harness_available_unavailable_status_is_false():
    readiness = _readiness(status="unavailable", inventory=_inventory({"pi"}))
    assert is_harness_available(readiness, "pi") is False


def test_harness_cli_unavailable_detail_is_stable_and_sanitized():
    readiness = _readiness(inventory=_inventory({"pi"}))
    detail = harness_cli_unavailable_detail(readiness, "claude")
    assert detail["code"] == "harness_cli_unavailable"
    assert detail["failure_code"] == "harness_cli_unavailable"
    assert detail["reason_code"] == REASON_NOT_SELECTED
    assert detail["kit_version"] == "0.4.0"
    assert "claude" in detail["message"]
    # no tokens, env values, payload paths or diagnostics
    assert "/opt/codify-kit" not in json.dumps(detail)


def test_harness_cli_unavailable_detail_unknown_reason_is_null():
    readiness = _readiness(
        inventory={"pi": {"availability": "present", "path": "/opt/codify-kit/harness/pi/bin/pi"}}
    )
    detail = harness_cli_unavailable_detail(readiness, "codex")
    assert detail["reason_code"] is None


def test_harness_cli_unavailable_error_carries_stable_fields():
    error = HarnessCliUnavailableError(
        harness_key="codex",
        reason_code=REASON_NOT_SELECTED,
        kit_version="0.4.0",
    )
    assert error.harness_key == "codex"
    assert error.reason_code == REASON_NOT_SELECTED
    assert error.kit_version == "0.4.0"
    assert "codex" in str(error)
    assert "0.4.0" in str(error)


def test_harness_cli_unavailable_error_maps_to_structured_task_failure():
    from unittest.mock import AsyncMock, MagicMock

    from app.core.worker_task_outcomes import fail_execute_task

    worker = MagicMock()
    worker._sanitize_sensitive_data = lambda value: value
    worker._try_upsert_usage_ledger = AsyncMock()
    worker._send_failure_notifications = AsyncMock()
    worker._quiesce_failed_container = AsyncMock(return_value=True)
    task = MagicMock()
    task.id = 1
    task.status = "running"
    task.completed_at = None
    task.container_id = None
    task.raw_logs_finalized_at = None
    task.retry_source_task_id = None

    import asyncio

    async def run():
        await fail_execute_task(
            worker,
            AsyncMock(),
            task,
            HarnessCliUnavailableError(
                harness_key="codex", reason_code=REASON_NOT_SELECTED, kit_version="0.4.0"
            ),
            had_existing_mr=False,
        )

    asyncio.run(run())
    parsed = json.loads(task.error_message)
    assert parsed["code"] == "harness_cli_unavailable"
    assert parsed["harness_key"] == "codex"
    assert parsed["reason_code"] == REASON_NOT_SELECTED
    assert parsed["kit_version"] == "0.4.0"
