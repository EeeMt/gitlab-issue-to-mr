"""Unit tests for the execution contract policy (phase1-design §2.3).

Covers mode validation (``dual_canary`` / ``v2_only``), the generic contract
eligibility and the exact-V2 requirement, legacy-snapshot detection, and the
unified ``legacy_contract_not_executable`` code used by scheduler remediation
and the worker-side fail-closed gate.
"""

from __future__ import annotations

import pytest

from app.core.harness_execution_policy import (
    LEGACY_CONTRACT_NOT_EXECUTABLE,
    ExecutionPolicyError,
    is_legacy_snapshot,
    is_v2_only,
    legacy_rejection_detail,
    require_creatable_bundle_v2,
    require_executable_contract,
    require_executable_contract_v2,
    require_explicit_harness_execution_mode,
    require_task_executable_contract,
    validate_harness_execution_mode,
)
from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA,
    CANONICAL_EVENT_SCHEMA_V2,
    HARNESS_CONTRACT_VERSION,
    HARNESS_CONTRACT_VERSION_V2,
)


class Bundle:
    def __init__(self, contract_version: str | None):
        self.contract_version = contract_version
        self.digest = "a" * 64
        self.manifest = {"adapters": {"pi": {}}}


class Attempt:
    def __init__(self, event_schema: str):
        self.event_schema = event_schema
        self.attempt_id = "attempt-1"
        self.harness_key = "pi"


class Snapshot:
    def __init__(self, contract_version: str | None):
        self.runtime_contract_version = contract_version
        self.runtime_bundle_digest = "a" * 64
        self.harness_key = "pi"


class Task:
    def __init__(self, contract_version: str | None):
        self.id = 7
        self.worker_profile_snapshot = Snapshot(contract_version)


# ── mode validation ─────────────────────────────────────────────────────────


def test_accepts_both_modes():
    validate_harness_execution_mode("dual_canary")
    validate_harness_execution_mode("v2_only")


def test_rejects_unknown_mode():
    with pytest.raises(ExecutionPolicyError) as exc:
        validate_harness_execution_mode("canary_only")
    assert exc.value.code == "invalid_harness_execution_mode"


def test_startup_requires_execution_mode_to_be_explicit():
    implicit = type(
        "Settings",
        (),
        {"harness_execution_mode": "dual_canary", "model_fields_set": set()},
    )()
    with pytest.raises(ExecutionPolicyError) as exc:
        require_explicit_harness_execution_mode(implicit)
    assert exc.value.code == "missing_harness_execution_mode"

    explicit = type(
        "Settings",
        (),
        {
            "harness_execution_mode": "dual_canary",
            "model_fields_set": {"harness_execution_mode"},
        },
    )()
    assert require_explicit_harness_execution_mode(explicit) == "dual_canary"


def test_is_v2_only_flag():
    assert is_v2_only("v2_only")
    assert not is_v2_only("dual_canary")


# ── generic contract eligibility ────────────────────────────────────────────


def test_contract_accepts_v1_and_v2_bundles():
    require_executable_contract(Bundle(HARNESS_CONTRACT_VERSION))
    require_executable_contract(Bundle(HARNESS_CONTRACT_VERSION_V2))


def test_contract_rejects_missing_or_unknown_version():
    with pytest.raises(ExecutionPolicyError) as exc:
        require_executable_contract(Bundle(None))
    assert exc.value.code == "missing_executable_contract"
    with pytest.raises(ExecutionPolicyError) as exc:
        require_executable_contract(Bundle("codify.worker.harness/v0"))
    assert exc.value.code == "missing_executable_contract"


# ── exact V2 requirement ────────────────────────────────────────────────────


def test_v2_contract_requires_exact_v2_attempt_and_bundle():
    require_executable_contract_v2(
        Attempt(CANONICAL_EVENT_SCHEMA_V2), Bundle(HARNESS_CONTRACT_VERSION_V2)
    )


def test_v2_contract_rejects_v1_attempt():
    with pytest.raises(ExecutionPolicyError) as exc:
        require_executable_contract_v2(
            Attempt(CANONICAL_EVENT_SCHEMA), Bundle(HARNESS_CONTRACT_VERSION_V2)
        )
    assert exc.value.code == LEGACY_CONTRACT_NOT_EXECUTABLE


def test_v2_contract_rejects_v1_bundle():
    with pytest.raises(ExecutionPolicyError) as exc:
        require_executable_contract_v2(
            Attempt(CANONICAL_EVENT_SCHEMA_V2), Bundle(HARNESS_CONTRACT_VERSION)
        )
    assert exc.value.code == LEGACY_CONTRACT_NOT_EXECUTABLE


def test_central_task_policy_validates_snapshot_bundle_and_attempt():
    task = Task(HARNESS_CONTRACT_VERSION_V2)
    bundle = Bundle(HARNESS_CONTRACT_VERSION_V2)
    require_task_executable_contract(
        task,
        bundle,
        "v2_only",
        attempt=Attempt(CANONICAL_EVENT_SCHEMA_V2),
    )


def test_central_task_policy_rejects_legacy_writer_under_v2_only():
    with pytest.raises(ExecutionPolicyError) as exc:
        require_task_executable_contract(
            Task(HARNESS_CONTRACT_VERSION),
            Bundle(HARNESS_CONTRACT_VERSION),
            "v2_only",
        )
    assert exc.value.code == LEGACY_CONTRACT_NOT_EXECUTABLE


def test_central_task_policy_rejects_snapshot_bundle_digest_mismatch():
    task = Task(HARNESS_CONTRACT_VERSION_V2)
    task.worker_profile_snapshot.runtime_bundle_digest = "b" * 64
    with pytest.raises(ExecutionPolicyError) as exc:
        require_task_executable_contract(
            task,
            Bundle(HARNESS_CONTRACT_VERSION_V2),
            "dual_canary",
        )
    assert exc.value.code == "execution_contract_mismatch"


# ── v2_only creation gate (F5) ──────────────────────────────────────────────


def test_creatable_bundle_v2_noop_outside_v2_only():
    # In dual_canary a legacy V1 bundle is still creatable.
    require_creatable_bundle_v2(Bundle(HARNESS_CONTRACT_VERSION), "dual_canary")


def test_creatable_bundle_v2_allows_canonical_v2_under_v2_only():
    require_creatable_bundle_v2(Bundle(HARNESS_CONTRACT_VERSION_V2), "v2_only")


def test_creatable_bundle_v2_rejects_v1_under_v2_only():
    with pytest.raises(ExecutionPolicyError) as exc:
        require_creatable_bundle_v2(Bundle(HARNESS_CONTRACT_VERSION), "v2_only")
    assert exc.value.code == LEGACY_CONTRACT_NOT_EXECUTABLE


def test_creatable_bundle_v2_rejects_missing_contract_under_v2_only():
    with pytest.raises(ExecutionPolicyError) as exc:
        require_creatable_bundle_v2(Bundle(None), "v2_only")
    assert exc.value.code == LEGACY_CONTRACT_NOT_EXECUTABLE


# ── legacy snapshot detection + rejection detail ────────────────────────────


def test_legacy_snapshot_detection():
    assert is_legacy_snapshot(type("S", (), {"runtime_contract_version": None})())
    assert is_legacy_snapshot(
        type("S", (), {"runtime_contract_version": HARNESS_CONTRACT_VERSION})()
    )
    assert not is_legacy_snapshot(
        type("S", (), {"runtime_contract_version": HARNESS_CONTRACT_VERSION_V2})()
    )


def test_legacy_rejection_detail_code():
    detail = legacy_rejection_detail(7)
    assert detail["code"] == LEGACY_CONTRACT_NOT_EXECUTABLE
    assert "v2_only" in detail["message"]


def test_config_settings_validates_harness_execution_mode():
    from pydantic import ValidationError

    from app.config import Settings

    assert Settings(harness_execution_mode="dual_canary").harness_execution_mode == "dual_canary"
    assert Settings(harness_execution_mode="v2_only").harness_execution_mode == "v2_only"
    with pytest.raises(ValidationError):
        Settings(harness_execution_mode="bogus")
