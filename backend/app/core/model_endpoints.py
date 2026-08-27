"""Model Endpoint normalization and secret-free fingerprinting.

An Endpoint is the non-secret configuration of a model provider. Task snapshots
freeze a ``model_endpoint_snapshot`` (never the API key/OAuth/cloud credential)
and a stable ``credential_ref`` pointing at an independently-rotatable
``ModelCredential``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.core.harness_registry import (
    runtime_bundle_model_protocols,
    validate_protocol_compatibility,
)

# v2: compatibility-meaningful inputs changed (model_protocol replaces the
# legacy protocol name, and compat_profile was added), so fingerprints must
# not mix with v1 values.
_FINGERPRINT_VERSION = "v2"

# Backend allowlist for compat_profile. This describes known differences of
# OpenAI-compatible services without creating a new protocol name per gateway.
# Unknown values are rejected at Task creation (see task_creation_service).
COMPAT_PROFILES = frozenset({"openai-compatible"})
MODEL_ENDPOINT_DEFAULT_MAX_TURNS = 20


@dataclass(frozen=True)
class ModelEndpoint:
    id: int | None
    name: str
    base_url: str
    model: str
    provider_kind: str
    model_protocol: str
    compat_profile: str | None = None
    provider_driver: str | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    credential_ref: str | None = None
    # These provider execution controls are frozen with the endpoint.  They
    # are optional only so snapshots written before this contract can still be
    # read through the legacy compatibility path.
    max_turns: int | None = None
    system_prompt: str | None = None

    @property
    def fingerprint(self) -> str:
        return endpoint_fingerprint(self)

    def as_snapshot(self) -> dict[str, Any]:
        """Secret-free snapshot frozen into a Task's worker profile snapshot."""
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "provider_kind": self.provider_kind,
            "model_protocol": self.model_protocol,
            "compat_profile": self.compat_profile,
            "provider_driver": self.provider_driver,
            "provider_options": self.provider_options,
            "credential_ref": self.credential_ref,
            "max_turns": self.max_turns,
            "system_prompt": self.system_prompt,
            "fingerprint": self.fingerprint,
        }


def _attr_str(obj: Any, name: str, default: str) -> str:
    value = getattr(obj, name, None)
    return value if isinstance(value, str) and value else default


def normalize_endpoint(provider: Any) -> ModelEndpoint:
    """Build a secret-free ModelEndpoint from an AIProvider ORM row."""
    provider_options = getattr(provider, "provider_options", None)
    if not isinstance(provider_options, dict):
        provider_options = {}
    credential_ref = getattr(provider, "credential_ref", None)
    if not isinstance(credential_ref, str):
        credential_ref = None
    compat_profile = getattr(provider, "compat_profile", None)
    if not isinstance(compat_profile, str) or not compat_profile:
        compat_profile = None
    # SQLAlchemy applies the AIProvider column default at INSERT/flush time.
    # Normalize the pre-flush object to the same value as the persisted row so
    # a Task snapshot cannot get a different endpoint fingerprint merely
    # because it was captured before the Provider was flushed (notably in the
    # CI auto-repair path).
    max_turns = getattr(provider, "max_turns", MODEL_ENDPOINT_DEFAULT_MAX_TURNS)
    if max_turns is None:
        max_turns = MODEL_ENDPOINT_DEFAULT_MAX_TURNS
    if not isinstance(max_turns, int) or isinstance(max_turns, bool):
        max_turns = None
    system_prompt = getattr(provider, "system_prompt", None)
    if system_prompt is not None and not isinstance(system_prompt, str):
        system_prompt = None
    return ModelEndpoint(
        id=getattr(provider, "id", None),
        name=_attr_str(provider, "name", ""),
        base_url=_attr_str(provider, "base_url", ""),
        model=_attr_str(provider, "model", ""),
        provider_kind=_attr_str(provider, "provider_kind", "anthropic_compatible"),
        model_protocol=_attr_str(provider, "model_protocol", "anthropic_messages"),
        compat_profile=compat_profile,
        provider_driver=_attr_str(provider, "provider_driver", None),
        provider_options=provider_options,
        credential_ref=credential_ref,
        max_turns=max_turns,
        system_prompt=system_prompt,
    )


def endpoint_fingerprint(endpoint: ModelEndpoint) -> str:
    """Stable, secret-free fingerprint over the compatibility domain.

    Only non-sensitive fields that affect harness/endpoint compatibility are
    included; keys are stably sorted and a version prefix lets the semantics
    evolve without silently mixing fingerprints across versions.
    """
    payload = {
        "provider_kind": endpoint.provider_kind,
        "model_protocol": endpoint.model_protocol,
        "compat_profile": endpoint.compat_profile,
        "provider_driver": endpoint.provider_driver,
        "base_url": endpoint.base_url,
        "model": endpoint.model,
        "provider_options": endpoint.provider_options,
    }
    # Keep the v2 fingerprint stable for snapshots created before provider
    # execution controls joined the frozen endpoint contract.  New snapshots
    # always carry max_turns, so both controls become part of their identity.
    if endpoint.max_turns is not None:
        payload.update(
            {
                "max_turns": endpoint.max_turns,
                "system_prompt": endpoint.system_prompt,
            }
        )
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"{_FINGERPRINT_VERSION}:{digest}"


def endpoint_transport_fingerprint(endpoint: ModelEndpoint) -> str:
    """Fingerprint only the live endpoint transport/configuration identity.

    A Provider's max-turn and system-prompt edits must not rewrite a queued
    Task's frozen execution policy, but they also must not be mistaken for a
    transport rebind.  The full ``fingerprint`` still identifies the complete
    frozen Task contract; this narrower value is used only when checking that
    the source Provider still points at the same endpoint.
    """
    payload = {
        "provider_kind": endpoint.provider_kind,
        "model_protocol": endpoint.model_protocol,
        "compat_profile": endpoint.compat_profile,
        "provider_driver": endpoint.provider_driver,
        "base_url": endpoint.base_url,
        "model": endpoint.model,
        "provider_options": endpoint.provider_options,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"{_FINGERPRINT_VERSION}:{digest}"


def ensure_harness_protocol_compatibility(
    harness_key: str,
    endpoint: ModelEndpoint,
    *,
    runtime_bundle: Any | None = None,
) -> None:
    """Reject a Harness/Endpoint pairing outside the frozen Bundle contract.

    Without a Bundle this validates the compile-time upper bound, which is
    appropriate before a new Task is bound.  Once a Bundle exists, its
    adapter declaration is authoritative and a historical subset must not be
    widened by today's source matrix.
    """
    allowed_protocols = (
        runtime_bundle_model_protocols(runtime_bundle, harness_key)
        if runtime_bundle is not None
        else None
    )
    validate_protocol_compatibility(
        harness_key,
        endpoint.model_protocol,
        allowed_protocols=allowed_protocols,
    )
