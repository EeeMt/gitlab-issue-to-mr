"""Tests for the built-in harness registry and capability policy."""

from __future__ import annotations

import pytest

from app.core.harness_registry import (
    HARNESS_KEYS,
    HarnessRegistryError,
    capability_policy,
    compatible_harness_keys,
    harness_options,
    validate_enabled_harnesses,
    validate_harness_constraints,
    validate_harness_key,
    validate_harness_runtimes,
    validate_protocol_compatibility,
    validate_runtime_bundle_manifest,
)


def test_registry_knows_claude_and_codex():
    assert HARNESS_KEYS == {"claude", "codex"}


def test_compatible_harness_keys_reverse_lookup():
    assert compatible_harness_keys("anthropic_messages") == ["claude"]
    assert compatible_harness_keys("openai_responses") == ["codex"]
    assert compatible_harness_keys(None) == ["claude"]
    assert compatible_harness_keys("openai_chat_completions") == []
    assert compatible_harness_keys("") == ["claude"]


def test_validate_harness_key_accepts_known_and_rejects_unknown():
    validate_harness_key("claude")
    validate_harness_key("codex")
    with pytest.raises(HarnessRegistryError):
        validate_harness_key("opencode")


@pytest.mark.parametrize(
    "enabled,default,ok",
    [
        (["claude"], "claude", True),
        (["claude", "codex"], "claude", True),
        (["claude"], "codex", False),  # default outside enabled
        ([], "claude", False),  # empty
        (["claude", "codex"], "opencode", False),  # unknown default
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
    manifest["adapters"]["opencode"] = {
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
        wire_protocol="anthropic_messages",
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
