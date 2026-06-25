from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.worker_profiles import (
    WorkerProfileValidationError,
    build_worker_profile_environment_map,
    parse_worker_profile_mounts,
    resolve_provider_for_issue,
    select_snapshot_run_instruction_template,
    serialize_profile_environment_variable_for_api,
    validate_worker_profile_mounts,
)


def test_validate_worker_profile_mounts_normalizes_mode():
    mounts = validate_worker_profile_mounts(
        [
            {"host_path": "/cache/m2", "container_path": "/home/codify/.m2", "mode": "rw"},
            {"host_path": "/certs/ca.crt", "container_path": "/etc/ssl/certs/custom-ca.crt"},
        ]
    )

    assert mounts == [
        {"host_path": "/cache/m2", "container_path": "/home/codify/.m2", "mode": "rw"},
        {
            "host_path": "/certs/ca.crt",
            "container_path": "/etc/ssl/certs/custom-ca.crt",
            "mode": "ro",
        },
    ]


def test_validate_worker_profile_mounts_rejects_bad_mode():
    with pytest.raises(WorkerProfileValidationError, match="mount mode"):
        validate_worker_profile_mounts(
            [
                {"host_path": "/cache", "container_path": "/cache", "mode": "bad"},
            ]
        )


def test_validate_worker_profile_mounts_rejects_duplicate_container_path():
    with pytest.raises(WorkerProfileValidationError, match="duplicate container mount path"):
        validate_worker_profile_mounts(
            [
                {"host_path": "/cache/a", "container_path": "/cache"},
                {"host_path": "/cache/b", "container_path": "/cache"},
            ]
        )


def test_parse_worker_profile_mounts_accepts_legacy_json_string():
    assert parse_worker_profile_mounts(
        '[{"host_path":"/a","container_path":"/b","mode":"rw"}]'
    ) == [
        {"host_path": "/a", "container_path": "/b", "mode": "rw"},
    ]


def test_build_worker_profile_environment_map_decrypts_secret(monkeypatch):
    rows = [
        {"key": "PLAIN_VALUE", "value": "plain", "is_secret": False},
        {"key": "SECRET_VALUE", "value": "encrypted", "is_secret": True},
    ]
    monkeypatch.setattr(
        "app.core.worker_profiles.decrypt_config_secret",
        lambda value: f"decrypted:{value}",
    )

    assert build_worker_profile_environment_map(rows) == {
        "PLAIN_VALUE": "plain",
        "SECRET_VALUE": "decrypted:encrypted",
    }


def test_build_worker_profile_environment_map_reuses_worker_env_key_validation():
    rows = [{"key": "GITLAB_TOKEN", "value": "leak", "is_secret": False}]

    with pytest.raises(WorkerProfileValidationError, match="reserved"):
        build_worker_profile_environment_map(rows)


def test_serialize_secret_profile_environment_variable_hides_plaintext():
    row = SimpleNamespace(
        id=7,
        key="SECRET_VALUE",
        value="encrypted-secret",
        is_secret=True,
        created_at=None,
        updated_at=None,
    )

    assert serialize_profile_environment_variable_for_api(row) == {
        "id": 7,
        "key": "SECRET_VALUE",
        "value": None,
        "is_secret": True,
        "value_configured": True,
        "created_at": None,
        "updated_at": None,
    }


def test_serialize_plain_empty_profile_environment_variable_is_configured():
    row = SimpleNamespace(
        id=8,
        key="EMPTY_VALUE",
        value="",
        is_secret=False,
        created_at=None,
        updated_at=None,
    )

    assert serialize_profile_environment_variable_for_api(row)["value_configured"] is True


@pytest.mark.asyncio
async def test_resolve_provider_for_issue_rejects_missing_configured_provider():
    db = SimpleNamespace()
    db.get = AsyncMock(return_value=None)
    default_provider = SimpleNamespace(id=1, name="Default Provider", is_disabled=False)
    default_result = SimpleNamespace(scalar_one_or_none=lambda: default_provider)
    db.execute = AsyncMock(return_value=default_result)
    issue = SimpleNamespace(default_provider_id=42)

    with pytest.raises(WorkerProfileValidationError, match="configured AI provider.*not found"):
        await resolve_provider_for_issue(db, issue)


def test_select_snapshot_run_instruction_template_uses_ci_template_for_ci_repair():
    snapshot = type(
        "Snapshot",
        (),
        {
            "default_execute_run_instruction_template": "execute {{user_prompt}}",
            "default_plan_run_instruction_template": "plan {{user_prompt}}",
            "ci_auto_repair_run_instruction_template": "repair {{issue_title}}",
        },
    )()

    assert (
        select_snapshot_run_instruction_template(
            snapshot,
            task_mode="execute",
            trigger_source="ci_auto_repair",
        )
        == "repair {{issue_title}}"
    )
