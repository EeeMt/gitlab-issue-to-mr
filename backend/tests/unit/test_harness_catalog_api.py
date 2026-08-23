from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import harness_catalog
from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2


def _manifest() -> dict:
    return {
        "schema": "codify.worker.runtime-manifest/v2",
        "maturity": "internal_preview",
        "contract_version": HARNESS_CONTRACT_VERSION_V2,
        "event_schema": "codify.worker.event/v2",
        "command_schema": "codify.worker.command/v2",
        "result_schema": "codify.worker.result/v2",
        "files": [],
        "adapters": {
            "pi": {
                "support_tier": "default",
                "adapter": {"version": "2.0.0", "digest": "a" * 64},
                "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
                "model_protocols": ["anthropic_messages"],
                "capabilities": {"steering": True, "follow_up": True},
                "options_schema": "pi/v1",
            }
        },
    }


def test_v2_catalog_is_safe_projection_without_source_metadata():
    manifest = _manifest()
    manifest["adapters"]["pi"]["source"] = {"path": "/secret/adapter"}

    result = harness_catalog._v2_catalog_response(
        SimpleNamespace(
            contract_version=HARNESS_CONTRACT_VERSION_V2,
            digest="b" * 64,
            manifest=manifest,
        ),
        source="task_runtime_bundle",
    )

    assert result["legacy"] is False
    assert result["bundle_digest"] == "b" * 64
    assert result["catalog"] == [
        {
            "key": "pi",
            "display_name": "Pi",
            "support_tier": "default",
            "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
            "model_protocols": ["anthropic_messages"],
            "capabilities": {"steering": True, "follow_up": True},
            "options_schema": "pi/v1",
        }
    ]
    assert "/secret" not in repr(result)


def test_legacy_catalog_is_read_only_and_empty():
    result = harness_catalog._legacy_catalog_response(
        SimpleNamespace(contract_version="codify.worker.harness/v1", digest="legacy")
    )
    assert result["legacy"] is True
    assert result["read_only"] is True
    assert result["catalog"] == []


def test_invalid_frozen_catalog_fails_closed():
    with pytest.raises(HTTPException) as raised:
        harness_catalog._v2_catalog_response(
            SimpleNamespace(
                contract_version=HARNESS_CONTRACT_VERSION_V2,
                digest="b" * 64,
                manifest={"adapters": {}},
            ),
            source="task_runtime_bundle",
        )
    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "invalid_runtime_bundle_catalog"


@pytest.mark.asyncio
async def test_task_catalog_uses_frozen_bundle_not_current_source(monkeypatch):
    bundle = SimpleNamespace(
        contract_version=HARNESS_CONTRACT_VERSION_V2,
        digest="b" * 64,
        manifest=_manifest(),
    )
    monkeypatch.setattr(
        harness_catalog,
        "get_task_with_access_check",
        lambda *args, **kwargs: _async_result(SimpleNamespace(runtime_bundle=bundle)),
    )

    result = await harness_catalog.get_task_harness_catalog(12, SimpleNamespace(), None, SimpleNamespace())

    assert result["source"] == "task_runtime_bundle"
    assert result["catalog"][0]["key"] == "pi"


async def _async_result(value):
    return value
