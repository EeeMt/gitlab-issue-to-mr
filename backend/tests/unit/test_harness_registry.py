"""Tests for the built-in harness registry and capability policy."""

from __future__ import annotations

import pytest

from app.core.harness_registry import (
    HARNESS_KEYS,
    HarnessRegistryError,
    capability_policy,
    compatible_harness_keys,
    harness_options,
    registry_catalog_from_manifest,
    validate_adapter_capabilities,
    validate_enabled_harnesses,
    validate_harness_constraints,
    validate_harness_key,
    validate_harness_runtimes,
    validate_protocol_compatibility,
    validate_runtime_bundle_manifest,
    validate_v2_manifest_adapter_capabilities,
)


def test_registry_knows_all_four_builtin_harnesses():
    assert {"pi", "opencode", "claude", "codex"} == HARNESS_KEYS


def test_compatible_harness_keys_reverse_lookup():
    # pi/opencode consume all three model protocols per the frozen V2 matrix.
    assert compatible_harness_keys("anthropic_messages") == ["claude", "opencode", "pi"]
    assert compatible_harness_keys("openai_responses") == ["codex", "opencode", "pi"]
    assert compatible_harness_keys(None) == ["claude", "opencode", "pi"]
    assert compatible_harness_keys("openai_chat_completions") == ["opencode", "pi"]
    assert compatible_harness_keys("") == ["claude", "opencode", "pi"]


def test_validate_adapter_capabilities_rejects_above_system_bound():
    # codex cannot support run_text (system bound False); a manifest claiming
    # it must fail the build rather than silently diverge.
    with pytest.raises(HarnessRegistryError, match="above the system upper bound"):
        validate_adapter_capabilities("codex", {"run_text": True})
    with pytest.raises(HarnessRegistryError, match="above the system upper bound"):
        validate_adapter_capabilities("codex", {"max_turns": True})


def test_validate_adapter_capabilities_allows_tightening_and_unknown():
    # Under-declaring (a supported capability not shipped) is a valid tighten.
    validate_adapter_capabilities("codex", {"run_text": False, "task_skills": True})
    # Unknown capabilities are forward-compatible and ignored.
    validate_adapter_capabilities("codex", {"future_capability": True})
    validate_adapter_capabilities("claude", {"run_text": True, "codegraph": True})


def test_validate_harness_key_accepts_known_and_rejects_unknown():
    for key in ("claude", "codex", "pi", "opencode"):
        validate_harness_key(key)
    with pytest.raises(HarnessRegistryError):
        validate_harness_key("omp")


@pytest.mark.parametrize(
    "enabled,default,ok",
    [
        (["claude"], "claude", True),
        (["claude", "codex"], "claude", True),
        (["claude"], "codex", False),  # default outside enabled
        ([], "claude", False),  # empty
        (["claude", "codex"], "opencode", False),  # default outside enabled
    ],
)
def test_validate_enabled_harnesses(enabled, default, ok):
    if ok:
        result = validate_enabled_harnesses(enabled, default_harness_key=default)
        assert result == enabled
    else:
        with pytest.raises(HarnessRegistryError):
            validate_enabled_harnesses(enabled, default_harness_key=default)


def test_validate_harness_constraints_allows_only_tightenable_keys():
    assert validate_harness_constraints({"max_turns": 10}) == {"max_turns": 10}
    assert validate_harness_constraints({"sandbox_mode": "sandboxed"}) == {
        "sandbox_mode": "sandboxed"
    }
    with pytest.raises(HarnessRegistryError):
        validate_harness_constraints({"unknown_limiter": 1})


def test_capability_policy_starts_from_system_upper_bound():
    policy = capability_policy("claude")
    assert policy["codegraph"] is True
    assert policy["sandbox_mode"] == "container-boundary"


def test_capability_policy_tightens_max_turns_and_rejects_relaxation():
    policy = capability_policy("claude", {"max_turns": 5})
    assert policy["max_turns"] == 5
    assert policy["max_turns_tightened"] is True
    with pytest.raises(HarnessRegistryError):
        capability_policy("claude", {"max_turns": 0})
    with pytest.raises(HarnessRegistryError):
        capability_policy("claude", {"unknown_limiter": 1})


def test_capability_policy_codex_marks_codegraph_disabled():
    policy = capability_policy("codex")
    assert policy["codegraph"] is False


def test_protocol_compatibility():
    validate_protocol_compatibility("claude", "anthropic_messages")
    validate_protocol_compatibility("codex", "openai_responses")
    with pytest.raises(HarnessRegistryError):
        validate_protocol_compatibility("claude", "openai_responses")
    with pytest.raises(HarnessRegistryError):
        validate_protocol_compatibility("codex", "anthropic_messages")


def _valid_manifest():
    return {
        "schema": "codify.worker.runtime-bundle/v1",
        "contract_version": "codify.worker.harness/v1",
        "event_schema": "codify.worker.event/v1",
        "orchestration_version": "1.0.0",
        "adapters": {
            "claude": {
                "version": "1.0.1",
                "digest": "d" * 64,
                "provider_protocols": ["anthropic_messages"],
                "capabilities": {"resume": True},
            }
        },
    }


def test_validate_runtime_bundle_manifest_accepts_known_adapter():
    validate_runtime_bundle_manifest(_valid_manifest())


def test_validate_runtime_bundle_manifest_rejects_mismatches():
    manifest = _valid_manifest()
    manifest["contract_version"] = "codify.worker.harness/v2"
    with pytest.raises(HarnessRegistryError):
        validate_runtime_bundle_manifest(manifest)

    manifest = _valid_manifest()
    manifest["adapters"]["claude"]["provider_protocols"] = ["openai_responses"]
    with pytest.raises(HarnessRegistryError):
        validate_runtime_bundle_manifest(manifest)

    manifest = _valid_manifest()
    del manifest["adapters"]["claude"]["digest"]
    with pytest.raises(HarnessRegistryError):
        validate_runtime_bundle_manifest(manifest)

    manifest = _valid_manifest()
    manifest["adapters"]["omp"] = {
        "version": "1.0.0",
        "digest": "d" * 64,
        "provider_protocols": ["anthropic_messages"],
    }
    with pytest.raises(HarnessRegistryError):
        validate_runtime_bundle_manifest(manifest)


def test_harness_options_reports_unavailable_codex():
    options = harness_options(
        enabled_harnesses=["claude", "codex"],
        default_harness_key="claude",
        available_harnesses=["claude"],
        model_protocol="anthropic_messages",
    )
    by_key = {opt["key"]: opt for opt in options}
    assert by_key["claude"]["selectable"] is True
    assert by_key["codex"]["selectable"] is False
    assert "adapter is not available" in by_key["codex"]["disabled_reason"]
    assert any("max_turns" in w for w in by_key["codex"]["warnings"])


def test_harness_options_codex_only_profile_is_unselectable():
    options = harness_options(
        enabled_harnesses=["codex"],
        default_harness_key="codex",
        available_harnesses=["claude"],
    )
    assert len(options) == 1
    assert options[0]["key"] == "codex"
    assert options[0]["selectable"] is False


def test_harness_runtimes_schema_is_restricted():
    assert validate_harness_runtimes(
        {"claude": {"source": "image", "executable_path": "/usr/local/bin/claude"}}
    ) == {"claude": {"source": "image", "executable_path": "/usr/local/bin/claude"}}
    with pytest.raises(HarnessRegistryError):
        validate_harness_runtimes({"claude": {"source": "docker exec rm -rf"}})
    with pytest.raises(HarnessRegistryError):
        validate_harness_runtimes({"unknown": {"source": "image"}})


# ── V2 manifest catalog ──────────────────────────────────────────────────────


def _v2_adapter(
    *,
    support_tier="default",
    artifact_version="0.84.2",
    control_kind="rpc_stdio",
    protocols=("anthropic_messages", "openai_responses", "openai_chat_completions"),
    capabilities=None,
    options_schema="pi/v1",
):
    return {
        "support_tier": support_tier,
        "source": {
            "repository": "https://github.com/earendil-works/pi",
            "license": "MIT",
            "artifact_version": artifact_version,
            "artifact_sha256": "aa" * 32,
        },
        "adapter": {"version": "2.0.0", "digest": "dd" * 32},
        "control_transport": {"kind": control_kind, "protocol": "pi-rpc"},
        "model_protocols": list(protocols),
        "capabilities": dict(capabilities)
        if capabilities is not None
        else {
            "resume": True,
            "task_skills": True,
            "usage_tokens": True,
            "steering": True,
            "follow_up": True,
        },
        "options_schema": options_schema,
    }


def _v2_manifest(**adapter_overrides):
    adapters = {
        "pi": _v2_adapter(),
        "opencode": _v2_adapter(
            control_kind="server_http",
            capabilities={
                "resume": True,
                "task_skills": True,
                "usage_tokens": True,
                "steering": False,
                "follow_up": False,
            },
            options_schema="opencode/v1",
        ),
        "claude": _v2_adapter(
            control_kind="cli_stream_json",
            protocols=("anthropic_messages",),
            capabilities={
                "resume": True,
                "task_skills": True,
                "usage_tokens": True,
                "steering": False,
                "follow_up": False,
            },
            options_schema=None,
        ),
        "codex": _v2_adapter(
            control_kind="cli_jsonl",
            protocols=("openai_responses",),
            capabilities={
                "resume": True,
                "task_skills": True,
                "usage_tokens": True,
                "steering": False,
                "follow_up": False,
            },
            options_schema=None,
        ),
    }
    for key, overrides in adapter_overrides.items():
        adapters[key] = {**adapters[key], **overrides}
    return {
        "schema": "codify.worker.runtime-manifest/v2",
        "maturity": "internal_preview",
        "contract_version": "codify.worker.harness/v2",
        "event_schema": "codify.worker.event/v2",
        "command_schema": "codify.worker.command/v2",
        "result_schema": "codify.worker.result/v2",
        "adapters": adapters,
        "files": [
            {"path": "harness/pi/bridge.py", "size": 10, "sha256": "aa" * 32},
            {"path": "harness/shared/schema.py", "size": 5, "sha256": "bb" * 32},
        ],
    }


def test_v2_capability_upper_bound_rejects_opencode_steering():
    # opencode cannot steer/follow_up per the frozen schema; a manifest claiming
    # steering=true above the code-held bound must fail closed.
    validate_v2_manifest_adapter_capabilities("opencode", {"steering": False})
    validate_v2_manifest_adapter_capabilities("pi", {"steering": True})
    with pytest.raises(HarnessRegistryError, match="above the system upper bound"):
        validate_v2_manifest_adapter_capabilities("opencode", {"steering": True})
    with pytest.raises(HarnessRegistryError, match="above the system upper bound"):
        validate_v2_manifest_adapter_capabilities("claude", {"follow_up": True})
    with pytest.raises(HarnessRegistryError, match="above the system upper bound"):
        validate_v2_manifest_adapter_capabilities("codex", {"follow_up": True})


def test_v2_capability_upper_bound_allows_tightening_and_unknown():
    # Under-declaring is a legitimate tightening; unknown keys are forward-compatible.
    validate_v2_manifest_adapter_capabilities("opencode", {"resume": False})
    validate_v2_manifest_adapter_capabilities("pi", {"future_capability": True})
    with pytest.raises(HarnessRegistryError):
        validate_v2_manifest_adapter_capabilities("unknown", {"steering": True})


def test_registry_catalog_is_displayable_and_never_leaks_source():
    catalog = {
        entry["key"]: entry for entry in registry_catalog_from_manifest(_v2_manifest())
    }
    assert set(catalog) == {"claude", "codex", "opencode", "pi"}
    pi = catalog["pi"]
    assert pi["display_name"] == "Pi"
    assert pi["support_tier"] == "default"
    assert pi["control_transport"]["kind"] == "rpc_stdio"
    assert "anthropic_messages" in pi["model_protocols"]
    assert pi["capabilities"]["steering"] is True
    assert pi["options_schema"] == "pi/v1"
    assert catalog["opencode"]["capabilities"]["steering"] is False
    assert catalog["claude"]["control_transport"]["kind"] == "cli_stream_json"
    assert catalog["codex"]["model_protocols"] == ["openai_responses"]

    # The catalog must never expose raw source commands / repository / artifacts.
    for entry in catalog.values():
        assert "repository" not in entry
        assert "source" not in entry
        assert "artifact_sha256" not in entry
        assert "executable" not in entry


def test_registry_catalog_rejects_capability_above_bound():
    manifest = _v2_manifest(
        opencode={
            "capabilities": {
                "resume": True,
                "task_skills": True,
                "usage_tokens": True,
                "steering": True,
                "follow_up": False,
            }
        }
    )
    with pytest.raises(HarnessRegistryError, match="above the system upper bound"):
        registry_catalog_from_manifest(manifest)


def test_registry_catalog_surfaces_options_schema_without_validator():
    # A schema name for which no typed validator exists yet (Task 6) is still
    # declared; Phase 1 exposes the catalog, it does not validate options.
    catalog = {
        entry["key"]: entry for entry in registry_catalog_from_manifest(_v2_manifest())
    }
    assert catalog["pi"]["options_schema"] == "pi/v1"
    assert catalog["opencode"]["options_schema"] == "opencode/v1"
    assert catalog["claude"]["options_schema"] is None
