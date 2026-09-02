"""Unit tests for the scheduler Harness availability gate (§11.3)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.worker_runtime_readiness import READINESS_READY, RuntimeReadiness

_SHA = "a" * 64


def _readiness(inventory: dict | None) -> RuntimeReadiness:
    return RuntimeReadiness(
        status=READINESS_READY,
        worker_kit_version="0.4.0",
        harness_inventory=inventory,
        kit_identity={"schema": "codify.worker.kit-identity/v1", "kit_version": "0.4.0", "platform": "linux/amd64", "manifest_sha256": _SHA},
    )


def _inventory(present: set[str]) -> dict:
    inventory = {}
    for key in ("pi", "opencode", "claude", "codex"):
        if key in present:
            inventory[key] = {
                "availability": "present",
                "path": f"/opt/codify-kit/harness/{key}/bin/{key}",
                "version": "1.0.0",
                "sha256": _SHA,
                "size": 1,
            }
        else:
            inventory[key] = {"availability": "absent", "reason_code": "not_selected"}
    return inventory


def _snapshot(*, cli_source: str | None, harness_key: str = "codex") -> SimpleNamespace:
    source = cli_source or "worker_kit"
    path = (
        f"/opt/codify-kit/harness/{harness_key}/bin/{harness_key}"
        if source == "worker_kit"
        else f"/usr/local/bin/{harness_key}"
    )
    cli = {
        "source": source,
        "executable_path": path,
        "version": "1.0.0",
        "binary_digest": _SHA,
    }
    image_identity = {
        "schema": "codify.worker-image-identity/v1",
        "daemon_key": "scheduler-gate-tests",
        "image_reference": "registry.example/worker@sha256:" + _SHA,
        "image_id": "sha256:" + _SHA,
        "runtime_platform": "linux/amd64",
    }
    return SimpleNamespace(
        harness_key=harness_key,
        runtime_mode="mounted_kit",
        runtime_contract_version="codify.worker.harness/v2",
        cli_source=cli_source,
        cli_executable_path=path,
        cli_version="1.0.0",
        cli_binary_digest=_SHA,
        harness_config_snapshot={
            "requested_runtime_contract_version": "codify.worker.harness/v2",
            "v2_worker_image_identity": image_identity,
            "worker_kit_identity": {
                "schema": "codify.worker.kit-identity/v1",
                "kit_version": "0.4.0",
                "platform": "linux/amd64",
                "manifest_sha256": _SHA,
            },
            "v2_harness_verification_evidence": {
                "image_identity": image_identity,
                "cli": cli,
            },
        },
    )


async def _run_gate(scheduler, db, snapshot, readiness):
    from app.scheduler import Scheduler

    bound = Scheduler._harness_availability_gate.__get__(scheduler, Scheduler)
    return await bound(db, MagicMock(), snapshot, readiness)


def _make_scheduler():
    scheduler = MagicMock()
    scheduler._emit_event = MagicMock()
    return scheduler


@pytest.mark.asyncio
async def test_gate_passes_for_present_inventory_harness():
    scheduler = _make_scheduler()
    db = AsyncMock()
    snapshot = _snapshot(cli_source="worker_kit", harness_key="pi")
    assert await _run_gate(scheduler, db, snapshot, _readiness(_inventory({"pi"}))) is False
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_gate_passes_for_authorized_host_mount_even_when_kit_absent():
    scheduler = _make_scheduler()
    db = AsyncMock()
    # codex is absent from the Kit inventory, but the frozen snapshot declares
    # an authorized host_mount break-glass: the gate must pass.
    snapshot = _snapshot(cli_source="host_mount", harness_key="codex")
    assert await _run_gate(scheduler, db, snapshot, _readiness(_inventory({"pi"}))) is False
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_gate_fails_absent_worker_kit_harness_with_stable_code():
    scheduler = _make_scheduler()
    db = AsyncMock()
    # ``AsyncSession.execute`` is async, but the returned SQLAlchemy Result's
    # ``scalar`` method is synchronous.  Configure the result explicitly so
    # the status-maintenance side effect does not create an un-awaited
    # AsyncMock coroutine or hide a test contract mismatch.
    db.execute.return_value = SimpleNamespace(scalar=lambda: 0)
    db.get.return_value = None
    snapshot = _snapshot(cli_source="worker_kit", harness_key="codex")
    db.commit = AsyncMock()
    task = MagicMock()
    task.id = 7
    task.status = "queued"
    task.completed_at = None
    task.issue_id = 3
    from app.scheduler import Scheduler

    bound = Scheduler._harness_availability_gate.__get__(scheduler, Scheduler)
    # The task fails deterministically with the stable harness_cli_unavailable
    # error; no container is created.
    assert (
        await bound(db, task, snapshot, _readiness(_inventory({"pi"})))
        is True
    )
    parsed = json.loads(task.error_message)
    assert parsed["code"] == "harness_cli_unavailable"
    assert parsed["harness_key"] == "codex"
    assert parsed["reason_code"] == "not_selected"
    scheduler._emit_event.assert_called_once()


@pytest.mark.asyncio
async def test_gate_ignores_v1_contracts():
    scheduler = _make_scheduler()
    db = AsyncMock()
    snapshot = SimpleNamespace(
        harness_key="claude",
        cli_source=None,
        harness_config_snapshot={"requested_runtime_contract_version": "codify.worker.harness/v1"},
    )
    assert await _run_gate(scheduler, db, snapshot, _readiness(_inventory({"pi"}))) is False
