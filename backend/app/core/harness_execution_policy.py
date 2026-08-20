"""Iteration-1 execution contract policy (phase1-design §2.3).

Gates whether a Task/attempt/Bundle is executable under the configured harness
execution mode. Two modes are supported:

- ``dual_canary`` (default): both canonical V1 bundles and V2 bundles are
  executable; V1 read paths stay available.
- ``v2_only``: fails closed. Only exact canonical V2 contracts run; any residual
  legacy V1 contract is not executable and is idempotently terminalized at
  startup/recovery with a unified ``legacy_contract_not_executable`` code.

The functions accept duck-typed objects (``event_schema``/``harness_key`` on an
attempt, ``contract_version`` on a bundle, ``runtime_contract_version`` on a
snapshot) so they are pure and unit-testable; the worker/scheduler call sites
pass the real ORM objects.
"""

from __future__ import annotations

from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA_V2,
    HARNESS_CONTRACT_VERSION,
    HARNESS_CONTRACT_VERSION_V2,
)

HARNESS_EXECUTION_MODES = frozenset({"dual_canary", "v2_only"})

# Unified code for a legacy V1 contract that is not executable (v2_only).
LEGACY_CONTRACT_NOT_EXECUTABLE = "legacy_contract_not_executable"


class ExecutionPolicyError(ValueError):
    """A contract cannot be executed under the active harness execution mode."""

    def __init__(self, message: str, *, code: str = LEGACY_CONTRACT_NOT_EXECUTABLE) -> None:
        super().__init__(message)
        self.code = code


def validate_harness_execution_mode(mode: str) -> str:
    """Validate a harness execution mode, raising on unknowns.

    Called by Backend and Scheduler at startup so a misconfigured deployment
    fails fast instead of silently running under the wrong policy.
    """
    if mode not in HARNESS_EXECUTION_MODES:
        raise ExecutionPolicyError(
            f"HARNESS_EXECUTION_MODE must be one of {sorted(HARNESS_EXECUTION_MODES)}; "
            f"got {mode!r}",
            code="invalid_harness_execution_mode",
        )
    return mode


def is_v2_only(mode: str) -> bool:
    """True when the mode is exactly ``v2_only``.

    A pure predicate: it never raises on an unknown mode. Strict validation of
    the mode string belongs in :func:`validate_harness_execution_mode`, which
    config/startup call to fail fast; runtime call sites (e.g. the worker
    container gate) treat anything that is not exactly ``v2_only`` as the
    permissive dual path.
    """
    return mode == "v2_only"


def _contract_is_v2(contract_version: str | None) -> bool:
    return contract_version == HARNESS_CONTRACT_VERSION_V2


def _attempt_is_v2(attempt) -> bool:
    return getattr(attempt, "event_schema", None) == CANONICAL_EVENT_SCHEMA_V2


def require_executable_contract(bundle) -> None:
    """Require an executable canonical contract on a bound Runtime Bundle.

    A bundle with no frozen contract is never executable. Both V1 and V2
    canonical contracts are executable in ``dual_canary``; the strict V2
    requirement is enforced separately by :func:`require_executable_contract_v2`
    at the points that need an exact V2 attempt.
    """
    version = getattr(bundle, "contract_version", None)
    if version not in (HARNESS_CONTRACT_VERSION, HARNESS_CONTRACT_VERSION_V2):
        raise ExecutionPolicyError(
            f"Runtime Bundle has no executable canonical contract "
            f"(contract_version={version!r})",
            code="missing_executable_contract",
        )


def require_executable_contract_v2(attempt, bundle) -> None:
    """Require an exact canonical V2 attempt AND a V2 Runtime Bundle."""
    require_executable_contract(bundle)
    if not _attempt_is_v2(attempt):
        raise ExecutionPolicyError(
            f"attempt {getattr(attempt, 'attempt_id', '?')} is not an exact V2 "
            f"attempt (event_schema={getattr(attempt, 'event_schema', None)!r})",
            code=LEGACY_CONTRACT_NOT_EXECUTABLE,
        )
    if getattr(bundle, "contract_version", None) != HARNESS_CONTRACT_VERSION_V2:
        raise ExecutionPolicyError(
            f"attempt {getattr(attempt, 'attempt_id', '?')} requires a V2 Runtime "
            f"Bundle (contract_version={getattr(bundle, 'contract_version', None)!r})",
            code=LEGACY_CONTRACT_NOT_EXECUTABLE,
        )


def is_legacy_snapshot(snapshot) -> bool:
    """True if a frozen Task snapshot pins a legacy V1 (or V1-carried) contract.

    A snapshot with ``runtime_contract_version == v2`` is V2 canonical; anything
    else (V1, null, unknown) is treated as legacy for startup remediation.
    """
    return not _contract_is_v2(getattr(snapshot, "runtime_contract_version", None))


def legacy_rejection_detail(attempt_or_task_id) -> dict:
    """Structured detail for the unified ``legacy_contract_not_executable`` code."""
    return {
        "code": LEGACY_CONTRACT_NOT_EXECUTABLE,
        "message": (
            "legacy V1 contract is not executable under HARNESS_EXECUTION_MODE="
            "v2_only; the container is stopped and the task terminalized"
        ),
        "subject": str(attempt_or_task_id),
    }
