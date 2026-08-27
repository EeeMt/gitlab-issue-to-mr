"""Tests for model endpoint normalization and fingerprinting."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.harness_registry import HarnessRegistryError
from app.core.model_endpoints import (
    ModelEndpoint,
    endpoint_transport_fingerprint,
    ensure_harness_protocol_compatibility,
    normalize_endpoint,
)


def _provider(**overrides):
    base = {
        "id": 1,
        "name": "ds",
        "base_url": "https://api.deepseek.com/anthropic",
        "model": "deepseek-v4-flash",
        "max_turns": 20,
        "system_prompt": None,
        "provider_kind": "anthropic_compatible",
        "model_protocol": "anthropic_messages",
        "compat_profile": None,
        "provider_driver": None,
        "provider_options": {"temperature": 0.2},
        "credential_ref": "cred-abc",
        "api_key": "encrypted-secret",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_normalize_endpoint_drops_secret():
    endpoint = normalize_endpoint(_provider())
    assert endpoint.credential_ref == "cred-abc"
    assert "api_key" not in endpoint.as_snapshot()
    assert "secret" not in endpoint.as_snapshot()


def test_fingerprint_is_stable_and_secret_free():
    a = normalize_endpoint(_provider())
    b = normalize_endpoint(_provider())
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint.startswith("v2:")
    assert "deepseek" not in a.fingerprint
    assert "api" not in a.fingerprint


def test_fingerprint_changes_on_compatibility_relevant_field():
    a = normalize_endpoint(_provider())
    b = normalize_endpoint(_provider(model_protocol="openai_responses"))
    assert a.fingerprint != b.fingerprint


def test_fingerprint_freezes_provider_execution_controls():
    a = normalize_endpoint(_provider(max_turns=20, system_prompt=None))
    b = normalize_endpoint(_provider(max_turns=21, system_prompt=None))
    c = normalize_endpoint(_provider(max_turns=20, system_prompt="Use concise output."))

    assert a.fingerprint != b.fingerprint
    assert a.fingerprint != c.fingerprint
    assert endpoint_transport_fingerprint(a) == endpoint_transport_fingerprint(b)
    assert endpoint_transport_fingerprint(a) == endpoint_transport_fingerprint(c)


def test_fingerprint_is_stable_before_provider_default_is_flushed():
    before_flush = normalize_endpoint(_provider(max_turns=None))
    after_flush = normalize_endpoint(_provider(max_turns=20))

    assert before_flush.max_turns == 20
    assert before_flush.fingerprint == after_flush.fingerprint
    assert before_flush.as_snapshot()["max_turns"] == 20


def test_fingerprint_changes_on_compat_profile():
    a = normalize_endpoint(_provider())
    b = normalize_endpoint(_provider(compat_profile="openai-compatible"))
    assert a.fingerprint != b.fingerprint
    # Changing compat_profile between two known values also changes the fingerprint.
    c = normalize_endpoint(
        _provider(model_protocol="openai_responses", compat_profile="openai-compatible")
    )
    d = normalize_endpoint(
        _provider(model_protocol="openai_responses", compat_profile=None)
    )
    assert c.fingerprint != d.fingerprint


def test_fingerprint_stable_when_compat_profile_absent():
    a = normalize_endpoint(_provider(compat_profile=None))
    b = normalize_endpoint(_provider())
    assert a.fingerprint == b.fingerprint


def test_fingerprint_ignores_irrelevant_ordering():
    a = normalize_endpoint(_provider(provider_options={"temperature": 0.2, "top_p": 1}))
    b = normalize_endpoint(_provider(provider_options={"top_p": 1, "temperature": 0.2}))
    assert a.fingerprint == b.fingerprint


def test_snapshot_carries_expected_fields():
    snapshot = normalize_endpoint(_provider()).as_snapshot()
    for key in (
        "id",
        "name",
        "base_url",
        "model",
        "provider_kind",
        "model_protocol",
        "compat_profile",
        "credential_ref",
        "max_turns",
        "system_prompt",
        "fingerprint",
    ):
        assert key in snapshot
    # The live snapshot must use the V2 name, never the legacy alias.
    assert "wire_protocol" not in snapshot
    assert snapshot["model_protocol"] == "anthropic_messages"
    assert snapshot["max_turns"] == 20
    assert snapshot["system_prompt"] is None


def test_normalize_endpoint_reads_model_protocol():
    endpoint = normalize_endpoint(_provider(model_protocol="openai_chat_completions"))
    assert endpoint.model_protocol == "openai_chat_completions"


def test_protocol_compatibility_endpoint_helper():
    endpoint = ModelEndpoint(
        id=1,
        name="ds",
        base_url="https://api.deepseek.com/anthropic",
        model="deepseek-v4-flash",
        provider_kind="anthropic_compatible",
        model_protocol="anthropic_messages",
    )
    ensure_harness_protocol_compatibility("claude", endpoint)
    with pytest.raises(HarnessRegistryError):
        ensure_harness_protocol_compatibility("codex", endpoint)
