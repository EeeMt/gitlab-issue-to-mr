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

from app.core.harness_registry import validate_protocol_compatibility

_FINGERPRINT_VERSION = "v1"


@dataclass(frozen=True)
class ModelEndpoint:
    id: int | None
    name: str
    base_url: str
    model: str
    provider_kind: str
    wire_protocol: str
    provider_driver: str | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    credential_ref: str | None = None

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
            "wire_protocol": self.wire_protocol,
            "provider_driver": self.provider_driver,
            "provider_options": self.provider_options,
            "credential_ref": self.credential_ref,
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
    return ModelEndpoint(
        id=getattr(provider, "id", None),
        name=_attr_str(provider, "name", ""),
        base_url=_attr_str(provider, "base_url", ""),
        model=_attr_str(provider, "model", ""),
        provider_kind=_attr_str(provider, "provider_kind", "anthropic_compatible"),
        wire_protocol=_attr_str(provider, "wire_protocol", "anthropic_messages"),
        provider_driver=_attr_str(provider, "provider_driver", None),
        provider_options=provider_options,
        credential_ref=credential_ref,
    )


def endpoint_fingerprint(endpoint: ModelEndpoint) -> str:
    """Stable, secret-free fingerprint over the compatibility domain.

    Only non-sensitive fields that affect harness/endpoint compatibility are
    included; keys are stably sorted and a version prefix lets the semantics
    evolve without silently mixing fingerprints across versions.
    """
    payload = {
        "provider_kind": endpoint.provider_kind,
        "wire_protocol": endpoint.wire_protocol,
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
    harness_key: str, endpoint: ModelEndpoint
) -> None:
    """Reject a harness/endpoint pairing that cannot speak to each other."""
    validate_protocol_compatibility(harness_key, endpoint.wire_protocol)
