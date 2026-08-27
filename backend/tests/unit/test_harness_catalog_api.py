from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import harness_catalog
from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2
from app.core.user_roles import PLATFORM_ROLE_USER
from app.core.worker_runtime_readiness import (
    READINESS_READY,
    READINESS_UNAVAILABLE,
    RuntimeReadiness,
)


@pytest.fixture(autouse=True)
def clear_app_dependency_overrides():
    yield
    from app.main import app

    app.dependency_overrides.clear()


def _catalog_app_client(
    mock_db,
    *,
    authenticated: bool = True,
    current_user: object | None = None,
    access_scope=None,
):
    from app.database import get_db
    from app.dependencies.auth import get_optional_current_user, require_authenticated_user
    from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
    from app.main import app

    async def override_db():
        yield mock_db

    def override_authentication():
        if not authenticated:
            raise HTTPException(status_code=401, detail="Authentication required")
        return current_user or SimpleNamespace(id=1, platform_role="platform_admin")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_authenticated_user] = override_authentication
    app.dependency_overrides[get_optional_current_user] = lambda: current_user
    app.dependency_overrides[require_project_access_scope] = lambda: (
        access_scope or ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
    )
    return TestClient(app, raise_server_exceptions=False)


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
    entry = result["catalog"][0]
    assert entry["key"] == "pi"
    assert entry["enabled"] is False
    assert entry["availability"] == "unknown"
    assert entry["selectable"] is False
    assert entry["disabled_reason"] == "worker_profile_unavailable"
    assert entry["availability_reason"] == "runtime_not_verified"
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
    assert result["catalog"][0]["enabled"] is False


def _catalog_entries() -> list[dict]:
    return [
        {
            "key": "pi",
            "display_name": "Pi",
            "support_tier": "default",
            "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
            "model_protocols": ["anthropic_messages"],
            "capabilities": {},
            "options_schema": "pi/v1",
        },
        {
            "key": "codex",
            "display_name": "Codex",
            "support_tier": "default",
            "control_transport": {"kind": "cli_jsonl", "protocol": "codex-jsonl"},
            "model_protocols": ["openai_responses"],
            "capabilities": {},
            "options_schema": "codex/v1",
        },
    ]


def test_catalog_separates_profile_enabled_from_present_inventory():
    result = harness_catalog._catalog_with_runtime_state(
        _catalog_entries(),
        profile=SimpleNamespace(
            enabled=True,
            enabled_harnesses=["pi"],
            harness_runtimes={},
        ),
        readiness=RuntimeReadiness(
            status=READINESS_READY,
            harness_inventory={
                "pi": {"availability": "present", "path": "/opt/codify-kit/harness/pi"},
                "codex": {"availability": "absent", "reason_code": "not_selected"},
            },
        ),
    )

    pi, codex = result
    assert pi["enabled"] is True
    assert pi["availability"] == "present"
    assert pi["selectable"] is True
    assert pi["availability_reason"] is None
    assert codex["enabled"] is False
    assert codex["availability"] == "unavailable"
    assert codex["disabled_reason"] == "harness_disabled"
    assert codex["availability_reason"] == "not_selected"
    assert "/opt/codify-kit" not in repr(result)


def test_catalog_marks_enabled_harness_unavailable_with_stable_reason():
    result = harness_catalog._catalog_with_runtime_state(
        _catalog_entries()[:1],
        profile=SimpleNamespace(
            enabled=True,
            enabled_harnesses=["pi"],
            harness_runtimes={},
        ),
        readiness=RuntimeReadiness(
            status=READINESS_READY,
            harness_inventory={
                "pi": {"availability": "absent", "reason_code": "missing_payload"},
            },
        ),
    )

    entry = result[0]
    assert entry["enabled"] is True
    assert entry["availability"] == "unavailable"
    assert entry["selectable"] is False
    assert entry["disabled_reason"] == "missing_payload"
    assert entry["reason_code"] == "missing_payload"


def test_catalog_keeps_unknown_runtime_selectable_but_explains_it():
    entry = harness_catalog._catalog_with_runtime_state(
        _catalog_entries()[:1],
        profile=SimpleNamespace(
            enabled=True,
            enabled_harnesses=["pi"],
            harness_runtimes={},
        ),
        readiness=RuntimeReadiness(status="unknown"),
    )[0]

    assert entry["availability"] == "unknown"
    assert entry["selectable"] is True
    assert entry["disabled_reason"] is None
    assert entry["availability_reason"] == "runtime_not_verified"


def test_catalog_uses_the_readiness_scope_for_each_harness():
    result = harness_catalog._catalog_with_runtime_state(
        _catalog_entries(),
        profile=SimpleNamespace(
            enabled=True,
            enabled_harnesses=["pi", "codex"],
            harness_runtimes={},
        ),
        readiness_by_harness={
            "pi": RuntimeReadiness(status=READINESS_UNAVAILABLE),
            "codex": RuntimeReadiness(
                status=READINESS_READY,
                harness_inventory={"codex": {"availability": "present"}},
            ),
        },
    )

    pi, codex = result
    assert pi["availability"] == "unavailable"
    assert pi["selectable"] is False
    assert codex["availability"] == "present"
    assert codex["selectable"] is True


@pytest.mark.asyncio
async def test_profile_readiness_keeps_mixed_v1_and_v2_scopes_separate(monkeypatch):
    profile = SimpleNamespace(
        enabled=True,
        enabled_harnesses=["claude", "pi"],
        harness_runtimes={
            "claude": {"contract_version": "codify.worker.harness/v1"},
            "pi": {"contract_version": HARNESS_CONTRACT_VERSION_V2},
        },
    )
    calls: list[str] = []

    async def fake_readiness(db, loaded_profile, settings, *, harness_key):
        calls.append(harness_key)
        if harness_key == "pi":
            return RuntimeReadiness(status=READINESS_UNAVAILABLE)
        return RuntimeReadiness(
            status=READINESS_READY,
            harness_inventory={harness_key: {"availability": "present"}},
        )

    monkeypatch.setattr(harness_catalog, "get_effective_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(harness_catalog, "readiness_for_profile", fake_readiness)

    result = await harness_catalog._catalog_readiness_by_harness_for_profile(
        SimpleNamespace(),
        profile,
        ["claude", "pi"],
    )

    assert calls == ["claude", "pi"]
    assert result["claude"].status == READINESS_READY
    assert result["pi"].status == READINESS_UNAVAILABLE


def test_frozen_catalog_uses_snapshot_harness_and_host_mount_without_path():
    bundle = SimpleNamespace(
        contract_version=HARNESS_CONTRACT_VERSION_V2,
        digest="b" * 64,
        manifest=_manifest(),
    )
    result = harness_catalog._v2_catalog_response(
        bundle,
        source="task_runtime_bundle",
        profile=SimpleNamespace(enabled=True, enabled_harnesses=["claude"]),
        snapshot=SimpleNamespace(harness_key="pi", cli_source="host_mount"),
    )

    entry = result["catalog"][0]
    assert entry["enabled"] is True
    assert entry["availability"] == "present"
    assert entry["selectable"] is True
    assert entry["availability_reason"] == "host_mount"
    assert "executable_path" not in repr(result)


def test_catalog_marks_unavailable_runtime_without_exposing_failure_message():
    entry = harness_catalog._catalog_with_runtime_state(
        _catalog_entries()[:1],
        profile=SimpleNamespace(
            enabled=True,
            enabled_harnesses=["pi"],
            harness_runtimes={},
        ),
        readiness=RuntimeReadiness(
            status=READINESS_UNAVAILABLE,
            failure_code="worker_kit_invalid",
            failure_message="secret host path /srv/kit",
        ),
    )[0]

    assert entry["availability"] == "unavailable"
    assert entry["disabled_reason"] == "worker_kit_unavailable"
    assert "secret host path" not in repr(entry)


@pytest.mark.asyncio
async def test_current_catalog_projects_requested_profile_runtime_state(monkeypatch):
    profile = SimpleNamespace(
        id=7,
        enabled=True,
        enabled_harnesses=["pi"],
        harness_runtimes={},
    )
    monkeypatch.setattr(harness_catalog, "_current_manifest", _manifest)
    monkeypatch.setattr(
        harness_catalog,
        "_load_catalog_profile",
        lambda db, worker_profile_id: _async_result(profile),
    )
    monkeypatch.setattr(
        harness_catalog,
        "_catalog_readiness_by_harness_for_profile",
        lambda db, loaded_profile, harness_keys: _async_result(
            {
                key: RuntimeReadiness(
                    status=READINESS_READY,
                    harness_inventory={key: {"availability": "present"}},
                )
                for key in harness_keys
            }
        ),
    )

    result = await harness_catalog.get_current_harness_catalog(
        worker_profile_id=7,
        db=SimpleNamespace(),
    )

    entry = result["catalog"][0]
    assert entry["enabled"] is True
    assert entry["availability"] == "present"
    assert entry["selectable"] is True


def test_current_catalog_route_requires_authentication():
    client = _catalog_app_client(MagicMock(), authenticated=False)

    response = client.get("/api/harness-catalog")

    assert response.status_code == 401


def test_current_catalog_route_returns_not_found_for_missing_profile(monkeypatch):
    db_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=db_result)
    monkeypatch.setattr(harness_catalog, "_current_manifest", _manifest)
    client = _catalog_app_client(mock_db)

    response = client.get("/api/harness-catalog?worker_profile_id=999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Worker profile 999 not found"


def test_task_catalog_route_denies_inaccessible_project_before_bundle_projection():
    task_result = MagicMock()
    task_result.scalar_one_or_none.return_value = SimpleNamespace(project_id=99)
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=task_result)
    from app.dependencies.project_access import ProjectAccessScope

    client = _catalog_app_client(
        mock_db,
        current_user=SimpleNamespace(id=1, platform_role=PLATFORM_ROLE_USER),
        access_scope=ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 1, "name": "allowed"}],
        ),
    )

    response = client.get("/api/tasks/42/harness-catalog")

    assert response.status_code == 403
    assert response.json()["detail"] == "Project 99 is not accessible for the current user"
    mock_db.execute.assert_awaited_once()


async def _async_result(value):
    return value
