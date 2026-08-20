"""Tests for V2 per-harness options: typed validators and deterministic merge."""

from __future__ import annotations

import pytest

from app.core.harness_options import (
    TASK_OVERRIDE_KEYS,
    HarnessOptionsError,
    deep_merge_options,
    validate_namespaced_options,
    validate_task_overrides,
)

# ── pi/v1 typed validator ─────────────────────────────────────────────────────

def test_pi_v1_rejects_unknown_keys():
    with pytest.raises(HarnessOptionsError):
        validate_namespaced_options({"pi": {"thinking_level": "high", "bogus": 1}})


def test_pi_v1_rejects_invalid_enum_value():
    with pytest.raises(HarnessOptionsError):
        validate_namespaced_options({"pi": {"thinking_level": "extreme"}})
    with pytest.raises(HarnessOptionsError):
        validate_namespaced_options({"pi": {"steering_mode": "parallel"}})


def test_pi_v1_accepts_valid_values():
    options = validate_namespaced_options(
        {"pi": {"thinking_level": "low", "steering_mode": "one-at-a-time"}}
    )
    assert options["pi"]["thinking_level"] == "low"
    assert options["pi"]["follow_up_mode"] == "one-at-a-time"  # default applied


# ── opencode/v1 typed validator ───────────────────────────────────────────────

def test_opencode_v1_validates_generic_options():
    options = validate_namespaced_options(
        {"opencode": {"agent": "build", "command": "test", "model_variant": "v1"}}
    )
    assert options["opencode"]["agent"] == "build"
    assert options["opencode"]["command"] == "test"


def test_opencode_v1_rejects_unknown_keys():
    with pytest.raises(HarnessOptionsError):
        validate_namespaced_options({"opencode": {"not_a_field": True}})


# ── unknown namespaces are tolerated (forward-compat) ─────────────────────────

def test_unknown_namespace_is_tolerated():
    options = validate_namespaced_options({"future": {"anything": 1}})
    assert options["future"] == {"anything": 1}


# ── task-override allowlist ───────────────────────────────────────────────────

def test_task_override_rejects_non_override_field():
    # opencode has no task_override fields -> any override rejected
    with pytest.raises(HarnessOptionsError):
        validate_task_overrides({"opencode": {"agent": "build"}})
    # pi: unknown field rejected
    with pytest.raises(HarnessOptionsError):
        validate_task_overrides({"pi": {"hidden_option": 1}})
    # pi: an allowed field passes
    validate_task_overrides({"pi": {"steering_mode": "one-at-a-time"}})


def test_task_override_accepts_only_flagged_fields():
    overrides = validate_task_overrides(
        {"pi": {"thinking_level": "high", "follow_up_mode": "one-at-a-time"}}
    )
    assert overrides["pi"]["thinking_level"] == "high"
    assert set(TASK_OVERRIDE_KEYS["pi/v1"]) == {
        "thinking_level",
        "steering_mode",
        "follow_up_mode",
    }


# ── deterministic deep merge ──────────────────────────────────────────────────

def test_deep_merge_profile_default_plus_task_override():
    # Profile defaults pass through the typed validator first (which applies
    # defaults), then the Task override is merged on top deterministically.
    profile = validate_namespaced_options(
        {
            "pi": {"thinking_level": "medium", "steering_mode": "one-at-a-time"},
            "opencode": {"agent": "build"},
        }
    )
    overrides = {"pi": {"thinking_level": "high"}}
    merged = deep_merge_options(profile, overrides)
    assert merged["pi"] == {
        "thinking_level": "high",
        "steering_mode": "one-at-a-time",
        "follow_up_mode": "one-at-a-time",  # default applied by validator
    }
    assert merged["opencode"] == {"agent": "build", "command": None, "model_variant": None}


def test_deep_merge_is_order_stable():
    profile = {
        "opencode": {"agent": "build"},
        "pi": {"thinking_level": "medium"},
    }
    a = deep_merge_options(profile, {})
    # Reversed insertion order yields the same key ordering.
    b = deep_merge_options(
        {"pi": {"thinking_level": "medium"}, "opencode": {"agent": "build"}}, {}
    )
    assert list(a.keys()) == list(b.keys())
    assert a == b
    # Explicitly sorted (deterministic).
    assert list(a.keys()) == sorted(a.keys())


def test_deep_merge_override_adds_new_namespace():
    merged = deep_merge_options({"pi": {"thinking_level": "medium"}}, {"opencode": {"agent": "x"}})
    assert "pi" in merged and merged["opencode"] == {"agent": "x"}


def test_deep_merge_empty_profile_is_empty():
    assert deep_merge_options(None, None) == {}
