"""Built-in Codify Harness registry and capability policy.

Only harness keys defined here are valid. Profiles may only tighten the
system capability upper bound; they can never relax sandbox/network/timeout
or secret policy. The frozen Runtime Bundle manifest is the single source of
truth for the actual Adapter version/digest and event protocol — this module
never accepts arbitrary commands or Adapter paths from the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA,
    HARNESS_CAPABILITY_KEYS,
    HARNESS_CONTRACT_VERSION,
    HARNESS_CONTRACT_VERSION_V2,
    HARNESS_PROTOCOL_MATRIX,
    MODEL_PROTOCOLS,
    validate_manifest,
)

# Known harness keys (compile-time allowlist). The V2 manifest catalog is
# restricted to this set; the frozen Runtime Bundle decides which of these
# keys is actually available for a Profile.
HARNESS_KEYS = frozenset({"pi", "opencode", "claude", "codex"})

# Re-export the V2 model-protocol allowlist for registry/API use.
MODEL_PROTOCOLS_ALLOWLIST = MODEL_PROTOCOLS

# Constraints a profile may tighten (never relax) per harness.
TIGHTENABLE_CONSTRAINTS = frozenset(
    {"max_turns", "sandbox_mode", "network_enabled", "timeout_seconds"}
)

# System upper-bound capabilities per harness. Profiles may only tighten these.
# This is the V1 capability matrix (run_text/codegraph/max_turns/...); it stays
# intact for the V1 path, with pi/opencode added to match the new allowlist.
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
    "pi": {
        "resume": True,
        "task_skills": True,
        "max_turns": True,
        "usage_tokens": True,
        "usage_cost": True,
        "run_text": True,
        "codegraph": True,
        "sandbox_mode": "container-boundary",
    },
    "opencode": {
        "resume": False,
        "task_skills": True,
        "max_turns": False,
        "usage_tokens": True,
        "usage_cost": True,
        "run_text": False,
        "codegraph": False,
        "sandbox_mode": "container-boundary",
    },
}

# V2 capability upper bound, keyed by HARNESS_CAPABILITY_KEYS
# (resume/task_skills/usage_tokens/steering/follow_up). The system upper bound
# stays in code; a manifest may only tighten it. Per the frozen schema: pi
# declares all four; opencode/claude/codex declare steering/follow_up=false.
V2_SYSTEM_CAPABILITY_UPPER_BOUND: dict[str, dict[str, bool]] = {
    "pi": {
        "resume": True,
        "task_skills": True,
        "usage_tokens": True,
        "steering": True,
        "follow_up": True,
    },
    "opencode": {
        "resume": False,
        "task_skills": True,
        "usage_tokens": True,
        "steering": False,
        "follow_up": False,
    },
    "claude": {
        "resume": True,
        "task_skills": True,
        "usage_tokens": True,
        "steering": False,
        "follow_up": False,
    },
    "codex": {
        "resume": True,
        "task_skills": True,
        "usage_tokens": True,
        "steering": False,
        "follow_up": False,
    },
}

# provider wire protocols each harness may consume.
HARNESS_PROVIDER_PROTOCOLS: dict[str, frozenset[str]] = {
    key: protocols for key, (_transport, protocols) in HARNESS_PROTOCOL_MATRIX.items()
}

DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude",
    "codex": "Codex",
    "pi": "Pi",
    "opencode": "OpenCode",
}


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

    Only the built-in schema is accepted: ``source`` in worker_kit|host_mount.
    ``worker_kit`` resolves the executable from the frozen Kit manifest's
    harness inventory, so it declares nothing else. ``host_mount`` is the
    explicit per-Harness break-glass: it must declare its executable path and
    may pin version/digest evidence. Arbitrary commands are rejected and an
    image/PATH fallback does not exist.
    """
    if not isinstance(runtimes, dict):
        raise HarnessRegistryError("harness_runtimes must be an object")
    for key, runtime in runtimes.items():
        validate_harness_key(key)
        if not isinstance(runtime, dict):
            raise HarnessRegistryError(
                f"harness_runtimes[{key!r}] must be an object"
            )
        source = runtime.get("source")
        if source not in {"worker_kit", "host_mount"}:
            raise HarnessRegistryError(
                f"harness_runtimes[{key!r}].source must be worker_kit|host_mount"
            )
        if source == "worker_kit":
            unknown = set(runtime) - {"source", "contract_version"}
            if unknown:
                raise HarnessRegistryError(
                    f"harness_runtimes[{key!r}] (worker_kit) has forbidden keys: "
                    f"{sorted(unknown)}; the executable path comes from the "
                    "frozen Worker Kit manifest"
                )
        else:
            unknown = set(runtime) - {
                "source",
                "executable_path",
                "version",
                "binary_digest",
                "contract_version",
            }
            if unknown:
                raise HarnessRegistryError(
                    f"harness_runtimes[{key!r}] has unknown keys: {sorted(unknown)}"
                )
            executable_path = runtime.get("executable_path")
            if not isinstance(executable_path, str) or not executable_path.startswith("/"):
                raise HarnessRegistryError(
                    f"harness_runtimes[{key!r}].executable_path must be an "
                    "absolute container path"
                )
        contract_version = runtime.get("contract_version")
        if contract_version is not None and contract_version not in {
            HARNESS_CONTRACT_VERSION,
            HARNESS_CONTRACT_VERSION_V2,
        }:
            raise HarnessRegistryError(
                f"harness_runtimes[{key!r}].contract_version must be "
                "codify.worker.harness/v1|v2"
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


def validate_protocol_compatibility(
    harness_key: str,
    model_protocol: str,
    *,
    allowed_protocols: Iterable[str] | None = None,
) -> None:
    validate_harness_key(harness_key)
    allowed = (
        frozenset(allowed_protocols)
        if allowed_protocols is not None
        else HARNESS_PROVIDER_PROTOCOLS[harness_key]
    )
    if model_protocol not in allowed:
        raise HarnessRegistryError(
            f"harness {harness_key!r} cannot consume model protocol {model_protocol!r}"
        )


def runtime_bundle_model_protocols(bundle: Any, harness_key: str) -> frozenset[str]:
    """Return the model protocols declared by one frozen Bundle adapter.

    ``HARNESS_PROTOCOL_MATRIX`` is only the code-held upper bound.  A Runtime
    Bundle may intentionally declare a strict subset (for example, a
    historical V2 Bundle whose Pi adapter predates OpenAI support), and that
    frozen declaration is the execution truth for a bound Task.  Never fall
    back to the current matrix when a Bundle is present but malformed.
    """
    validate_harness_key(harness_key)
    manifest = getattr(bundle, "manifest", None)
    if not isinstance(manifest, Mapping):
        raise HarnessRegistryError("Runtime Bundle has no valid manifest")
    adapters = manifest.get("adapters")
    if not isinstance(adapters, Mapping):
        raise HarnessRegistryError("Runtime Bundle manifest has no adapters")
    adapter = adapters.get(harness_key)
    if not isinstance(adapter, Mapping):
        raise HarnessRegistryError(
            f"Runtime Bundle manifest has no adapter for harness {harness_key!r}"
        )
    protocols = adapter.get("model_protocols")
    if protocols is None:
        # V1 Runtime Bundles used the provider_protocols spelling.  Keep the
        # compatibility reader explicit while preserving the same fail-closed
        # semantics for malformed historical rows.
        protocols = adapter.get("provider_protocols")
    if not isinstance(protocols, list) or not protocols:
        raise HarnessRegistryError(
            f"Runtime Bundle adapter {harness_key!r} has no model protocols"
        )
    normalized: set[str] = set()
    for protocol in protocols:
        if not isinstance(protocol, str) or not protocol.strip():
            raise HarnessRegistryError(
                f"Runtime Bundle adapter {harness_key!r} has an invalid model protocol"
            )
        protocol = protocol.replace("-", "_")
        if protocol not in MODEL_PROTOCOLS:
            raise HarnessRegistryError(
                f"Runtime Bundle adapter {harness_key!r} declares unsupported "
                f"model protocol {protocol!r}"
            )
        normalized.add(protocol)
    unsupported = normalized - HARNESS_PROVIDER_PROTOCOLS[harness_key]
    if unsupported:
        raise HarnessRegistryError(
            f"Runtime Bundle adapter {harness_key!r} declares model protocols "
            f"outside the approved harness bound: {sorted(unsupported)}"
        )
    return frozenset(normalized)


def compatible_harness_keys(model_protocol: str | None) -> list[str]:
    """Harness keys whose Adapter can consume the given model protocol.

    Backend-computed reverse lookup so the Frontend never reimplements the
    harness/Endpoint compatibility matrix. A null protocol defaults to the
    legacy Claude model protocol, matching endpoint normalization.
    """
    if not model_protocol:
        model_protocol = "anthropic_messages"
    return sorted(
        key
        for key, protocols in HARNESS_PROVIDER_PROTOCOLS.items()
        if model_protocol in protocols
    )


def validate_adapter_capabilities(
    harness_key: str, capabilities: dict[str, Any]
) -> None:
    """Reject an Adapter manifest that declares a capability above the system bound.

    ``SYSTEM_CAPABILITIES`` is the upper bound the platform will allow; the
    frozen Runtime Bundle manifest must never claim support the system forbids
    (e.g. codex ``run_text``). Under-declaring (a capability the system allows
    but the Adapter does not ship) is a legitimate tightening and stays valid.
    """
    validate_harness_key(harness_key)
    if not isinstance(capabilities, dict):
        raise HarnessRegistryError(
            f"adapter {harness_key!r} capabilities must be an object"
        )
    upper = SYSTEM_CAPABILITIES[harness_key]
    for name, value in capabilities.items():
        if name not in upper or not isinstance(upper[name], bool):
            # Unknown capabilities are forward-compatible (readers ignore
            # them); non-boolean bounds (e.g. sandbox_mode) are handled by
            # capability_policy tightening.
            continue
        if value is True and upper[name] is False:
            raise HarnessRegistryError(
                f"adapter {harness_key!r} declares capability {name!r} "
                "above the system upper bound"
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
        capabilities = adapter.get("capabilities")
        if capabilities is not None:
            validate_adapter_capabilities(key, capabilities)
        # The V1 host manifest uses ``provider_protocols``; the v2-ready
        # ``opencode`` block carries ``model_protocols`` instead. Accept either
        # so a v2-ready block validates in place without a model_protocols copy.
        protocols = adapter.get("provider_protocols", adapter.get("model_protocols"))
        if not isinstance(protocols, list) or not protocols:
            raise HarnessRegistryError(
                f"adapter {key!r} has no provider_protocols/model_protocols"
            )
        allowed = HARNESS_PROVIDER_PROTOCOLS[key]
        for protocol in protocols:
            if protocol.replace("-", "_") not in allowed:
                raise HarnessRegistryError(
                    f"adapter {key!r} declares unsupported protocol {protocol!r}"
                )


def validate_v2_manifest_adapter_capabilities(
    harness_key: str, capabilities: Mapping[str, Any]
) -> None:
    """Reject a V2 manifest capability the system upper bound forbids.

    ``V2_SYSTEM_CAPABILITY_UPPER_BOUND`` is the code-held ceiling keyed by
    ``HARNESS_CAPABILITY_KEYS``; a manifest may only tighten it, never raise it.
    Under-declaring a supported capability or declaring an unknown
    (forward-compatible) key is legitimate and stays valid.
    """
    validate_harness_key(harness_key)
    if not isinstance(capabilities, Mapping):
        raise HarnessRegistryError(
            f"adapter {harness_key!r} V2 capabilities must be an object"
        )
    upper = V2_SYSTEM_CAPABILITY_UPPER_BOUND[harness_key]
    for name, value in capabilities.items():
        if name not in HARNESS_CAPABILITY_KEYS:
            # Unknown capabilities are forward-compatible (readers ignore them).
            continue
        if value is True and upper.get(name) is False:
            raise HarnessRegistryError(
                f"adapter {harness_key!r} declares V2 capability {name!r} "
                "above the system upper bound"
            )


def registry_catalog_from_manifest(
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project a validated V2 runtime-manifest into a *displayable* catalog.

    Returns one displayable entry per approved adapter: key, display name,
    support tier, control transport, model protocols, capabilities and options
    schema. It never leaks ``source.repository`` commands, artifact paths or
    host paths — only supporting metadata is exposed. ``options_schema`` names
    the schema even when no typed validator exists yet (Phase 1 declares the
    catalog; typed validators for pi/v1 and opencode/v1 are a later responsibility).

    System capability upper bounds stay in code; every adapter's declared V2
    capabilities are checked against the bound before being returned.
    """
    validated = validate_manifest(manifest)
    adapters = validated["adapters"]
    entries: list[dict[str, Any]] = []
    for key in sorted(adapters):
        adapter = adapters[key]
        capabilities = adapter.get("capabilities") or {}
        validate_v2_manifest_adapter_capabilities(key, capabilities)
        entries.append(
            {
                "key": key,
                "display_name": DISPLAY_NAMES.get(key, key),
                "support_tier": adapter.get("support_tier"),
                "control_transport": dict(adapter.get("control_transport") or {}),
                "model_protocols": list(adapter.get("model_protocols") or []),
                "capabilities": dict(capabilities),
                "options_schema": adapter.get("options_schema"),
            }
        )
    return entries


def harness_options(
    *,
    enabled_harnesses: Iterable[str],
    default_harness_key: str,
    available_harnesses: Iterable[str] = ("claude",),
    model_protocol: str | None = None,
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
        elif model_protocol is not None:
            try:
                validate_protocol_compatibility(key, model_protocol)
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
