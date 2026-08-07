"""Built-in Codify Harness registry and capability policy.

Only harness keys defined here are valid. Profiles may only tighten the
system capability upper bound; they can never relax sandbox/network/timeout
or secret policy. The frozen Runtime Bundle manifest is the single source of
truth for the actual Adapter version/digest and event protocol — this module
never accepts arbitrary commands or Adapter paths from the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA,
    HARNESS_CONTRACT_VERSION,
)

# Known harness keys. codex is a first-class key even though its adapter is not
# yet bundled; profiles cannot select a harness whose adapter is unavailable.
HARNESS_KEYS = frozenset({"claude", "codex"})

# Constraints a profile may tighten (never relax) per harness.
TIGHTENABLE_CONSTRAINTS = frozenset(
    {"max_turns", "sandbox_mode", "network_enabled", "timeout_seconds"}
)

# System upper-bound capabilities per harness. Profiles may only tighten these.
SYSTEM_CAPABILITIES: dict[str, dict[str, Any]] = {
    "claude": {
        "resume": True,
        "task_skills": True,
        "max_turns": True,
        "usage_tokens": True,
        "usage_cost": True,
        "run_text": True,
        "codegraph": True,
        "sandbox_mode": "container-boundary",
    },
    "codex": {
        "resume": True,
        "task_skills": True,
        "max_turns": False,
        "usage_tokens": True,
        "usage_cost": True,
        "run_text": False,
        "codegraph": False,
        "sandbox_mode": "container-boundary",
    },
}

# provider wire protocols each harness may consume.
HARNESS_PROVIDER_PROTOCOLS: dict[str, frozenset[str]] = {
    "claude": frozenset({"anthropic_messages"}),
    "codex": frozenset({"openai_responses"}),
}

DISPLAY_NAMES: dict[str, str] = {"claude": "Claude", "codex": "Codex"}


class HarnessRegistryError(ValueError):
    """Invalid harness selection or constraint."""


@dataclass(frozen=True)
class HarnessOption:
    key: str
    display_name: str
    selectable: bool
    disabled_reason: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "selectable": self.selectable,
            "disabled_reason": self.disabled_reason,
            "capabilities": self.capabilities,
            "warnings": self.warnings,
        }


def validate_harness_key(key: str) -> None:
    if key not in HARNESS_KEYS:
        raise HarnessRegistryError(f"unknown harness key: {key!r}")


def validate_enabled_harnesses(
    enabled: Iterable[str], *, default_harness_key: str
) -> list[str]:
    enabled_list = list(dict.fromkeys(enabled))
    if not enabled_list:
        raise HarnessRegistryError("enabled_harnesses must not be empty")
    for key in enabled_list:
        validate_harness_key(key)
    validate_harness_key(default_harness_key)
    if default_harness_key not in enabled_list:
        raise HarnessRegistryError(
            f"default_harness_key {default_harness_key!r} must be in enabled_harnesses"
        )
    return enabled_list


def validate_harness_runtimes(runtimes: dict[str, Any]) -> dict[str, Any]:
    """Validate the per-harness CLI runtime declarations on a Profile.

    Only the built-in schema is accepted: ``source`` in image|host_mount plus
    executable path/version/binary digest. Arbitrary commands are rejected.
    """
    if not isinstance(runtimes, dict):
        raise HarnessRegistryError("harness_runtimes must be an object")
    for key, runtime in runtimes.items():
        validate_harness_key(key)
        if not isinstance(runtime, dict):
            raise HarnessRegistryError(
                f"harness_runtimes[{key!r}] must be an object"
            )
        allowed = {"source", "executable_path", "version", "binary_digest"}
        unknown = set(runtime) - allowed
        if unknown:
            raise HarnessRegistryError(
                f"harness_runtimes[{key!r}] has unknown keys: {sorted(unknown)}"
            )
        source = runtime.get("source")
        if source not in {"image", "host_mount"}:
            raise HarnessRegistryError(
                f"harness_runtimes[{key!r}].source must be image|host_mount"
            )
    return runtimes


def validate_harness_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(constraints, dict):
        raise HarnessRegistryError("harness_constraints must be an object")
    unknown = set(constraints) - TIGHTENABLE_CONSTRAINTS
    if unknown:
        raise HarnessRegistryError(
            f"cannot constrain harness on: {sorted(unknown)}"
        )
    return constraints


def capability_policy(
    harness_key: str, constraints: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Effective capabilities = system upper bound, tightened by profile."""
    validate_harness_key(harness_key)
    upper = SYSTEM_CAPABILITIES[harness_key]
    constraints = constraints or {}
    validate_harness_constraints(constraints)

    effective = dict(upper)
    if "max_turns" in constraints:
        max_turns = constraints["max_turns"]
        if max_turns is not None:
            if not isinstance(max_turns, int) or max_turns < 1:
                raise HarnessRegistryError("max_turns must be a positive integer")
            effective["max_turns"] = max_turns
            effective["max_turns_tightened"] = True
    if "sandbox_mode" in constraints:
        mode = constraints["sandbox_mode"]
        allowed = {"container-boundary", "sandboxed"}
        if mode not in allowed:
            raise HarnessRegistryError(f"unknown sandbox_mode: {mode!r}")
        effective["sandbox_mode"] = mode
    if "network_enabled" in constraints:
        effective["network_enabled"] = bool(constraints["network_enabled"])
    if "timeout_seconds" in constraints:
        timeout = constraints["timeout_seconds"]
        if timeout is not None:
            if not isinstance(timeout, int) or timeout < 1:
                raise HarnessRegistryError("timeout_seconds must be a positive integer")
            effective["timeout_seconds"] = timeout
    return effective


def validate_protocol_compatibility(harness_key: str, wire_protocol: str) -> None:
    validate_harness_key(harness_key)
    if wire_protocol not in HARNESS_PROVIDER_PROTOCOLS[harness_key]:
        raise HarnessRegistryError(
            f"harness {harness_key!r} cannot consume wire protocol {wire_protocol!r}"
        )


def compatible_harness_keys(wire_protocol: str | None) -> list[str]:
    """Harness keys whose Adapter can consume the given wire protocol.

    Backend-computed reverse lookup so the Frontend never reimplements the
    harness/Endpoint compatibility matrix. A null protocol defaults to the
    legacy Claude wire protocol, matching endpoint normalization.
    """
    if not wire_protocol:
        wire_protocol = "anthropic_messages"
    return sorted(
        key
        for key, protocols in HARNESS_PROVIDER_PROTOCOLS.items()
        if wire_protocol in protocols
    )


def validate_runtime_bundle_manifest(manifest: dict[str, Any]) -> None:
    """Validate a frozen Runtime Bundle manifest against the harness contract."""
    if manifest.get("contract_version") != HARNESS_CONTRACT_VERSION:
        raise HarnessRegistryError(
            "Runtime Bundle contract does not match the harness contract"
        )
    if manifest.get("event_schema") != CANONICAL_EVENT_SCHEMA:
        raise HarnessRegistryError(
            "Runtime Bundle event schema does not match the canonical event schema"
        )
    adapters = manifest.get("adapters")
    if not isinstance(adapters, dict) or not adapters:
        raise HarnessRegistryError("Runtime Bundle manifest has no adapters")
    for key, adapter in adapters.items():
        validate_harness_key(key)
        if not isinstance(adapter, dict):
            raise HarnessRegistryError(f"adapter {key!r} is not an object")
        if not adapter.get("version"):
            raise HarnessRegistryError(f"adapter {key!r} has no version")
        if not adapter.get("digest"):
            raise HarnessRegistryError(f"adapter {key!r} has no digest")
        protocols = adapter.get("provider_protocols")
        if not isinstance(protocols, list) or not protocols:
            raise HarnessRegistryError(
                f"adapter {key!r} has no provider_protocols"
            )
        allowed = HARNESS_PROVIDER_PROTOCOLS[key]
        for protocol in protocols:
            if protocol.replace("-", "_") not in allowed:
                raise HarnessRegistryError(
                    f"adapter {key!r} declares unsupported protocol {protocol!r}"
                )


def harness_options(
    *,
    enabled_harnesses: Iterable[str],
    default_harness_key: str,
    available_harnesses: Iterable[str] = ("claude",),
    wire_protocol: str | None = None,
) -> list[dict[str, Any]]:
    """Compatibility-return structure consumed directly by the Frontend.

    ``available_harnesses`` is the set of harness keys whose adapter exists in
    the frozen Runtime Bundle; a harness in the profile allowlist but without
    an available adapter is reported as not selectable.
    """
    enabled = list(enabled_harnesses)
    available = set(available_harnesses)
    options: list[HarnessOption] = []
    for key in HARNESS_KEYS:
        if key not in enabled:
            continue
        capabilities = capability_policy(key)
        warnings: list[str] = []
        disabled_reason: str | None = None
        if key not in available:
            disabled_reason = f"{DISPLAY_NAMES[key]} adapter is not available"
        elif wire_protocol is not None:
            try:
                validate_protocol_compatibility(key, wire_protocol)
            except HarnessRegistryError as exc:
                disabled_reason = str(exc)
        if key == "codex":
            warnings.append(
                "Codex does not support max_turns or CodeGraph; "
                "wall-clock timeout applies"
            )
        options.append(
            HarnessOption(
                key=key,
                display_name=DISPLAY_NAMES[key],
                selectable=disabled_reason is None,
                disabled_reason=disabled_reason,
                capabilities=capabilities,
                warnings=warnings,
                # codex declared but not yet bundled -> not selectable
            )
        )
    if not options:
        raise HarnessRegistryError(
            f"profile enables no known harness; default={default_harness_key!r}"
        )
    return [option.as_dict() for option in options]
