"""Typed validators and deterministic merge for V2 per-harness options.

Worker Profiles store namespaced ``harness_options`` like::

    {"pi": {...}, "opencode": {...}, "claude": ..., "codex": ...}

Each known options-schema namespace (``pi/v1``, ``opencode/v1``) is validated
with a typed Pydantic validator that rejects unknown keys and invalid enum
values. Unknown schema names are *tolerated* for forward-compatibility — Phase 1
declares the catalog but later harnesses (e.g. ``claude``/``codex``) do not yet
ship a typed validator — so a profile may carry extra namespaces that are passed
through untouched.

Task creation only accepts overrides for fields the manifest marks
``task_override=true``.  Because the V2 runtime manifest is not yet wired into
task creation, that rule is implemented against an in-code options-schema table
here.  A Profile default and any Task override are deterministically deep-merged
(sorted keys, stable order) and frozen into ``harness_config_snapshot``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# ── Options-schema registry ────────────────────────────────────────────────────

# namespace (Profile key) -> options-schema name (manifest `options_schema`)
NS_TO_OPTIONS_SCHEMA = {
    "pi": "pi/v1",
    "opencode": "opencode/v1",
}

# Fields a Task may override for each options-schema, mirroring the manifest
# `task_override=true` flag.  These are deliberately small, fixed-version
# allowlists: arbitrary OpenCode config is never accepted from a Task request.
TASK_OVERRIDE_KEYS: dict[str, frozenset[str]] = {
    "pi/v1": frozenset({"thinking_level", "steering_mode", "follow_up_mode"}),
    "opencode/v1": frozenset({"agent", "command", "model_variant"}),
}

OPENCODE_AGENT_ALLOWLIST = frozenset({"build", "plan", "general", "explore"})
OPENCODE_COMMAND_ALLOWLIST = frozenset({"codify"})
_OPENCODE_MODEL_VARIANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


# ── Typed validators ───────────────────────────────────────────────────────────

class PiV1Options(BaseModel):
    """Options schema ``pi/v1`` (see open-harness-v2 phase1 design §5.4)."""

    model_config = ConfigDict(extra="forbid")

    thinking_level: str = Field(default="medium")
    steering_mode: str = Field(default="one-at-a-time")
    follow_up_mode: str = Field(default="one-at-a-time")

    @field_validator("thinking_level")
    @classmethod
    def _thinking(cls, v: str) -> str:
        allowed = {"none", "low", "medium", "high"}
        if v not in allowed:
            raise ValueError(f"thinking_level must be one of {sorted(allowed)}")
        return v

    @field_validator("steering_mode", "follow_up_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        # One-at-a-time is the only ship mode for the first release; others
        # remain outside the schema.
        allowed = {"one-at-a-time"}
        if v not in allowed:
            raise ValueError(f"mode must be one of {sorted(allowed)}")
        return v


class OpenCodeV1Options(BaseModel):
    """Options schema ``opencode/v1`` (see open-harness-v2 phase3 design §7.3).

    Only the fixed 1.18.19 native fields with a controlled Codify mapping are
    exposed. ``model_variant`` is an identifier rather than arbitrary JSON: the
    selected value is carried in the frozen Snapshot and passed to the pinned
    Server request unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    agent: str = Field(default="build")
    command: str | None = Field(default=None)
    model_variant: str | None = Field(default=None)

    @field_validator("agent")
    @classmethod
    def _agent(cls, value: str) -> str:
        if value not in OPENCODE_AGENT_ALLOWLIST:
            raise ValueError(f"agent must be one of {sorted(OPENCODE_AGENT_ALLOWLIST)}")
        return value

    @field_validator("command")
    @classmethod
    def _command(cls, value: str | None) -> str | None:
        if value is not None and value not in OPENCODE_COMMAND_ALLOWLIST:
            raise ValueError(
                f"command must be null or one of {sorted(OPENCODE_COMMAND_ALLOWLIST)}"
            )
        return value

    @field_validator("model_variant")
    @classmethod
    def _model_variant(cls, value: str | None) -> str | None:
        if value is not None and not _OPENCODE_MODEL_VARIANT_RE.fullmatch(value):
            raise ValueError(
                "model_variant must be null or a 1-64 character safe identifier"
            )
        return value



OPTION_VALIDATORS: dict[str, type[BaseModel]] = {
    "pi/v1": PiV1Options,
    "opencode/v1": OpenCodeV1Options,
}


# ── Validation / merge helpers ─────────────────────────────────────────────────

class HarnessOptionsError(ValueError):
    """Raised when a Profile's harness_options or a Task override is invalid."""


def validate_namespaced_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate a Profile's namespaced ``harness_options``.

    Each known options-schema namespace is validated by its typed validator;
    unknown namespaces are passed through unchanged (forward-compatible).  Keys
    are preserved as given (callers canonicalize at freeze time).
    """
    if not options:
        return {}
    if not isinstance(options, dict):
        raise HarnessOptionsError("harness_options must be an object")
    validated: dict[str, Any] = {}
    for namespace, value in options.items():
        schema = NS_TO_OPTIONS_SCHEMA.get(namespace)
        if schema is None or schema not in OPTION_VALIDATORS:
            # Unknown schema: tolerate for forward-compat.
            validated[namespace] = value
            continue
        if not isinstance(value, dict):
            raise HarnessOptionsError(
                f"harness_options['{namespace}'] must be an object"
            )
        try:
            validated[namespace] = OPTION_VALIDATORS[schema](**value).model_dump(
                exclude_none=False
            )
        except ValidationError as exc:
            raise HarnessOptionsError(
                f"invalid harness_options['{namespace}'][{schema}]: {exc}"
            ) from exc
    return validated


def validate_task_overrides(
    overrides: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate Task-level option overrides against the task_override allowlist.

    ``overrides`` is namespaced like Profile options (``{"pi": {...}}``).  Any
    field not marked ``task_override=true`` is rejected.  Unknown option
    namespaces are tolerated for forward-compat.
    """
    if not overrides:
        return {}
    if not isinstance(overrides, dict):
        raise HarnessOptionsError("task harness overrides must be an object")
    validated: dict[str, Any] = {}
    for namespace, value in overrides.items():
        schema = NS_TO_OPTIONS_SCHEMA.get(namespace)
        if schema is None or schema not in OPTION_VALIDATORS:
            continue
        if not isinstance(value, dict):
            raise HarnessOptionsError(
                f"harness override['{namespace}'] must be an object"
            )
        allowed = TASK_OVERRIDE_KEYS.get(schema, frozenset())
        unknown = set(value) - set(allowed)
        if unknown:
            raise HarnessOptionsError(
                f"harness override for '{namespace}' fields not allowed for "
                f"task override: {sorted(unknown)} (allowed: {sorted(allowed)})"
            )
        try:
            # Preserve the partial shape of a Task override.  Calling
            # ``model_dump()`` with defaults would turn an override containing
            # only ``agent`` into an implicit reset of command/variant.
            validated[namespace] = OPTION_VALIDATORS[schema](**value).model_dump(
                exclude_unset=True,
                exclude_none=False,
            )
        except ValidationError as exc:
            raise HarnessOptionsError(
                f"invalid harness override['{namespace}'][{schema}]: {exc}"
            ) from exc
    return validated


def deep_merge_options(
    profile_options: Mapping[str, Any] | None,
    task_overrides: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Deterministic deep-merge of Profile defaults with a Task's overrides.

    The result only contains namespaces/keys present after merge and uses
    ``json.dumps(sort_keys=True)``-stable ordering so the frozen snapshot (and
    its digest) is reproducible across runs.  Unknown namespaces are carried
    through verbatim.

    Rules:
      * overrides shallowly override per-namespace; within a namespace the
        override map is merged on top of the profile default for that namespace;
      * namespaces only present in overrides are added;
      * absent values are omitted; an explicit null in an override is retained
        so optional Profile defaults (for example OpenCode command/variant) can
        be intentionally cleared.
    """
    profile = dict(profile_options or {})
    overrides = dict(task_overrides or {})
    merged: dict[str, Any] = {}
    for namespace in sorted(set(profile) | set(overrides)):
        base = profile.get(namespace)
        override = overrides.get(namespace)
        if override is not None:
            # Override wins wherever present.
            if isinstance(base, dict) and isinstance(override, dict):
                merged[namespace] = {**base, **override}
            else:
                merged[namespace] = override
        elif base is not None:
            merged[namespace] = base
    return dict(sorted(merged.items()))
