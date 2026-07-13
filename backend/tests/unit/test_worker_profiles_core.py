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
    serialize_worker_profile_for_api,
    snapshot_from_profile,
    validate_worker_profile_docker_target,
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


@pytest.mark.parametrize(
    ("mount", "message"),
    [
        (
            {"host_path": "cache", "container_path": "/cache"},
            "host_path must be absolute",
        ),
        (
            {"host_path": "/cache", "container_path": "cache"},
            "container_path must be absolute",
        ),
    ],
)
def test_validate_worker_profile_mounts_requires_absolute_paths(mount, message):
    with pytest.raises(WorkerProfileValidationError, match=message):
        validate_worker_profile_mounts([mount])


def test_validate_worker_profile_mounts_normalizes_paths_before_duplicate_check():
    with pytest.raises(WorkerProfileValidationError, match="duplicate host mount path"):
        validate_worker_profile_mounts(
            [
                {"host_path": "/cache", "container_path": "/cache/one"},
                {"host_path": "/cache/.", "container_path": "/cache/two"},
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


def test_validate_worker_profile_mounts_rejects_duplicate_host_path():
    with pytest.raises(WorkerProfileValidationError, match="duplicate host mount path"):
        validate_worker_profile_mounts(
            [
                {"host_path": "/cache", "container_path": "/cache/one"},
                {"host_path": "/cache", "container_path": "/cache/two"},
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


def test_build_worker_profile_environment_map_can_omit_secrets(monkeypatch):
    rows = [
        {"key": "PLAIN_VALUE", "value": "plain", "is_secret": False},
        {"key": "SECRET_VALUE", "value": "encrypted", "is_secret": True},
    ]
    decrypt = AsyncMock()
    monkeypatch.setattr("app.core.worker_profiles.decrypt_config_secret", decrypt)

    assert build_worker_profile_environment_map(rows, include_secrets=False) == {
        "PLAIN_VALUE": "plain",
    }
    decrypt.assert_not_called()


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


def test_worker_profile_serialization_and_snapshot_preserve_codegraph_toggle():
    profile = SimpleNamespace(
        id=9,
        name="CodeGraph Worker",
        description=None,
        enabled=True,
        is_default=False,
        image="codify-worker/java21-maven:2026.07",
        codegraph_enabled=True,
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="execute {{user_prompt}}",
        default_plan_run_instruction_template="plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="repair {{issue_title}}",
        created_at=None,
        updated_at=None,
    )
    task = SimpleNamespace(id=44)

    assert serialize_worker_profile_for_api(profile)["codegraph_enabled"] is True
    snapshot = snapshot_from_profile(task, profile)
    assert snapshot.codegraph_enabled is True


def test_worker_profile_docker_target_is_admin_only_and_snapshotted():
    profile = SimpleNamespace(
        id=9,
        name="ARM Worker",
        description=None,
        enabled=True,
        is_default=False,
        image="worker:arm64",
        docker_host="tcp://arm-worker:2376",
        docker_tls_ca="/certs/ca.pem",
        docker_tls_cert="/certs/cert.pem",
        docker_tls_key="/certs/key.pem",
        codegraph_enabled=False,
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="execute {{user_prompt}}",
        default_plan_run_instruction_template="plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="repair {{issue_title}}",
        created_at=None,
        updated_at=None,
    )

    assert "docker_host" not in serialize_worker_profile_for_api(profile)
    admin_payload = serialize_worker_profile_for_api(profile, include_docker_target=True)
    assert admin_payload["docker_host"] == "tcp://arm-worker:2376"
    snapshot = snapshot_from_profile(SimpleNamespace(id=44), profile)
    assert snapshot.docker_host == "tcp://arm-worker:2376"
    assert snapshot.docker_tls_key == "/certs/key.pem"


def test_system_docker_profile_snapshots_resolved_deployment_target():
    profile = SimpleNamespace(
        id=10,
        name="System Worker",
        image="worker:latest",
        docker_host=None,
        docker_tls_ca=None,
        docker_tls_cert=None,
        docker_tls_key=None,
        codegraph_enabled=False,
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="execute {{user_prompt}}",
        default_plan_run_instruction_template="plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="repair {{issue_title}}",
    )
    settings = SimpleNamespace(
        docker_host="tcp://system-worker:2376",
        docker_tls_ca="/system/ca.pem",
        docker_tls_cert="/system/cert.pem",
        docker_tls_key="/system/key.pem",
    )

    snapshot = snapshot_from_profile(
        SimpleNamespace(id=45),
        profile,
        settings=settings,
    )

    assert snapshot.docker_host == "tcp://system-worker:2376"
    assert snapshot.docker_tls_ca == "/system/ca.pem"
    assert snapshot.docker_tls_cert == "/system/cert.pem"
    assert snapshot.docker_tls_key == "/system/key.pem"


def test_validate_worker_profile_docker_target_requires_complete_absolute_tls_paths():
    with pytest.raises(WorkerProfileValidationError, match="configured together"):
        validate_worker_profile_docker_target(
            docker_host="tcp://worker:2376",
            docker_tls_ca="/certs/ca.pem",
            docker_tls_cert=None,
            docker_tls_key=None,
        )

    with pytest.raises(WorkerProfileValidationError, match="absolute"):
        validate_worker_profile_docker_target(
            docker_host="tcp://worker:2376",
            docker_tls_ca="certs/ca.pem",
            docker_tls_cert="/certs/cert.pem",
            docker_tls_key="/certs/key.pem",
        )

    assert validate_worker_profile_docker_target(
        docker_host=" tcp://worker:2376 ",
        docker_tls_ca=" /certs/ca.pem ",
        docker_tls_cert=" /certs/cert.pem ",
        docker_tls_key=" /certs/key.pem ",
    ) == (
        "tcp://worker:2376",
        "/certs/ca.pem",
        "/certs/cert.pem",
        "/certs/key.pem",
    )


@pytest.mark.parametrize(
    "docker_host",
    [
        "http://worker:2376",
        "ssh://worker",
        "npipe:////./pipe/docker_engine",
    ],
)
def test_validate_worker_profile_docker_target_rejects_unsupported_mvp_protocols(
    docker_host,
):
    with pytest.raises(WorkerProfileValidationError, match="unix, tcp, or https"):
        validate_worker_profile_docker_target(
            docker_host=docker_host,
            docker_tls_ca=None,
            docker_tls_cert=None,
            docker_tls_key=None,
        )


@pytest.mark.parametrize("docker_host", ["tcp://", "https://", "unix://"])
def test_validate_worker_profile_docker_target_rejects_incomplete_endpoints(docker_host):
    with pytest.raises(WorkerProfileValidationError):
        validate_worker_profile_docker_target(
            docker_host=docker_host,
            docker_tls_ca=None,
            docker_tls_cert=None,
            docker_tls_key=None,
        )


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
