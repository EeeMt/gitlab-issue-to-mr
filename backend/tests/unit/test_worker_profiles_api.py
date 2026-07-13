from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.worker_profiles import (
    DockerConnectionTestRequest,
    WorkerProfileCreateRequest,
    WorkerProfileEnvironmentVariableRequest,
    WorkerRuntimeVerificationRequest,
    create_worker_profile,
    set_default_worker_profile_endpoint,
    verify_worker_profile_runtime,
)
from app.api.worker_profiles import (
    test_worker_profile_docker_connection as run_docker_connection_test,
)
from app.database import get_db
from app.dependencies.auth import (
    require_admin_user,
    require_authenticated_user,
)
from app.main import app
from app.models import Base


def _make_profile(
    *,
    id=1,
    name="Default Worker",
    enabled=True,
    is_default=False,
    environment_variables=None,
):
    return SimpleNamespace(
        id=id,
        name=name,
        description=None,
        enabled=enabled,
        is_default=is_default,
        image="codify-worker/java21-maven:2026.07",
        runtime_mode="baked_image",
        worker_kit_version=None,
        worker_kit_path=None,
        docker_host="tcp://worker:2376",
        docker_tls_ca="/certs/ca.pem",
        docker_tls_cert="/certs/cert.pem",
        docker_tls_key="/certs/key.pem",
        codegraph_enabled=False,
        volume_mounts=[],
        environment_variables=environment_variables or [],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


@pytest.mark.asyncio
async def test_create_worker_profile_rejects_duplicate_env_keys():
    db = MagicMock()
    db.add = MagicMock()
    name_check_result = MagicMock()
    name_check_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=name_check_result)
    db.flush = AsyncMock()
    db.rollback = AsyncMock()

    request = WorkerProfileCreateRequest(
        name="Java Worker",
        image="codify-worker-java:latest",
        volume_mounts=[],
        environment_variables=[
            WorkerProfileEnvironmentVariableRequest(key="MAVEN_OPTS", value="-Xmx1g"),
            WorkerProfileEnvironmentVariableRequest(key="MAVEN_OPTS", value="-Xmx2g"),
        ],
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
    )

    with pytest.raises(HTTPException) as exc:
        await create_worker_profile(request, db=db)
    assert exc.value.status_code == 422
    assert "Duplicate worker environment variable key" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_create_worker_profile_returns_created_profile_after_commit_without_lazy_load():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        request = WorkerProfileCreateRequest(
            name="Java Worker",
            image="codify-worker-java:latest",
            codegraph_enabled=True,
            volume_mounts=[],
            environment_variables=[
                WorkerProfileEnvironmentVariableRequest(key="JAVA_OPTS", value="-Xmx1g")
            ],
            default_execute_run_instruction_template="Execute {{user_prompt}}",
            default_plan_run_instruction_template="Plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        )

        response = await create_worker_profile(request, db=db)

    await engine.dispose()

    assert response["name"] == "Java Worker"
    assert response["image"] == "codify-worker-java:latest"
    assert response["codegraph_enabled"] is True
    assert response["environment_variables"][0]["key"] == "JAVA_OPTS"


@pytest.mark.asyncio
async def test_create_mounted_worker_profile_persists_portable_kit_contract():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        request = WorkerProfileCreateRequest(
            name="External Java Runtime",
            image="team/java21-maven:2026.07",
            runtime_mode="mounted_kit",
            worker_kit_version="0.1.0",
            worker_kit_path="/opt/codify/worker-kits/0.1.0-linux-amd64",
            volume_mounts=[],
            environment_variables=[],
            default_execute_run_instruction_template="Execute {{user_prompt}}",
            default_plan_run_instruction_template="Plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        )

        response = await create_worker_profile(request, db=db)

    await engine.dispose()

    assert response["runtime_mode"] == "mounted_kit"
    assert response["worker_kit_version"] == "0.1.0"
    assert response["worker_kit_path"] == "/opt/codify/worker-kits/0.1.0-linux-amd64"


@pytest.mark.asyncio
async def test_create_mounted_worker_profile_rejects_kit_mount_collision():
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)
    db.rollback = AsyncMock()

    request = WorkerProfileCreateRequest(
        name="Invalid Runtime",
        image="team/node22:2026.07",
        runtime_mode="mounted_kit",
        worker_kit_version="0.1.0",
        worker_kit_path="/opt/codify/worker-kits/0.1.0-linux-amd64",
        volume_mounts=[
            {"host_path": "/tmp/override", "container_path": "/nix", "mode": "rw"}
        ],
        environment_variables=[],
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
    )

    with pytest.raises(HTTPException) as exc:
        await create_worker_profile(request, db=db)

    assert exc.value.status_code == 422
    assert "conflicts with worker-kit path" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_set_default_rejects_disabled_profile():
    profile = _make_profile(id=10, name="Disabled Worker", enabled=False)

    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await set_default_worker_profile_endpoint(
            profile_id=10,
            db=db,
        )
    assert exc.value.status_code == 422
    assert "Disabled worker profiles cannot be default" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_verify_mounted_worker_profile_runs_preflight_on_profile_target():
    profile = _make_profile(
        id=12,
        name="Java Runtime",
        environment_variables=[
            SimpleNamespace(
                key="CODIFY_CLAUDE_BIN",
                value="/usr/local/bin/claude",
                is_secret=False,
            ),
            SimpleNamespace(
                key="RUNTIME_SECRET",
                value="encrypted-value",
                is_secret=True,
            ),
        ],
    )
    profile.image = "team/java21-maven:2026.07"
    profile.runtime_mode = "mounted_kit"
    profile.worker_kit_version = "0.1.0"
    profile.worker_kit_path = "/opt/codify/worker-kits/0.1.0-linux-amd64"
    profile.volume_mounts = [
        {
            "host_path": "/opt/codify/overrides/claude",
            "container_path": "/usr/local/bin/claude",
            "mode": "ro",
        }
    ]
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)

    container = MagicMock()
    client = MagicMock()
    client.create_container.return_value = container
    client.wait_for_container.return_value = (0, "Worker kit verification passed")

    with patch("app.api.worker_profiles.DockerClientWrapper", return_value=client):
        response = await verify_worker_profile_runtime(
            12,
            WorkerRuntimeVerificationRequest(smoke_command="java -version"),
            db=db,
        )

    assert response["ok"] is True
    assert response["image"] == "team/java21-maven:2026.07"
    client.client.images.get.assert_called_once_with("team/java21-maven:2026.07")
    create_kwargs = client.create_container.call_args.kwargs
    assert create_kwargs["command"] == ["--verify", "--smoke", "java -version"]
    assert create_kwargs["entrypoint"] == "/opt/codify-kit/launcher"
    assert create_kwargs["user"] == "0:0"
    assert create_kwargs["tmpfs"] == {"/workspace": "rw,exec,mode=1777"}
    assert create_kwargs["environment"]["CODIFY_CLAUDE_BIN"] == "/usr/local/bin/claude"
    assert "RUNTIME_SECRET" not in create_kwargs["environment"]
    assert response["omitted_secret_environment_keys"] == ["RUNTIME_SECRET"]
    assert create_kwargs["volumes"]["/opt/codify/overrides/claude"] == {
        "bind": "/usr/local/bin/claude",
        "mode": "ro",
    }
    assert create_kwargs["volumes"][profile.worker_kit_path] == {
        "bind": "/opt/codify-kit",
        "mode": "ro",
    }
    assert create_kwargs["volumes"][f"{profile.worker_kit_path}/nix/store"] == {
        "bind": "/nix/store",
        "mode": "ro",
    }
    container.remove.assert_called_once_with(force=True)
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_verify_baked_worker_profile_is_rejected_without_docker_access():
    profile = _make_profile(id=13)
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)

    with (
        patch("app.api.worker_profiles.DockerClientWrapper") as client_class,
        pytest.raises(HTTPException) as exc,
    ):
        await verify_worker_profile_runtime(
            13,
            WorkerRuntimeVerificationRequest(),
            db=db,
        )

    assert exc.value.status_code == 422
    assert "mounted_kit" in str(exc.value.detail)
    client_class.assert_not_called()


def test_list_worker_profiles_exposes_secret_configured_not_plaintext():
    secret_row = SimpleNamespace(
        id=20,
        key="SECRET_VALUE",
        value="encrypted-secret",
        is_secret=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    profile = _make_profile(id=3, environment_variables=[secret_row])

    result = MagicMock()
    result.scalars.return_value.all.return_value = [profile]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/api/worker-profiles")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    env_item = response.json()[0]["environment_variables"][0]
    assert env_item["value"] is None
    assert env_item["value_configured"] is True
    assert "encrypted-secret" not in response.text
    assert "docker_host" not in response.json()[0]


def test_admin_worker_profile_list_includes_docker_target():
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_make_profile(id=3)]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/api/worker-profiles/admin")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["docker_host"] == "tcp://worker:2376"


@pytest.mark.asyncio
async def test_worker_profile_docker_connection_returns_server_identity():
    docker = MagicMock()
    docker.inspect_server.return_value = {
        "server_version": "27.1.0",
        "architecture": "aarch64",
        "operating_system": "Linux",
    }
    settings = SimpleNamespace(
        docker_host="unix:///var/run/docker.sock",
        docker_tls_ca=None,
        docker_tls_cert=None,
        docker_tls_key=None,
    )
    with (
        patch("app.api.worker_profiles.get_effective_settings", return_value=settings),
        patch("app.api.worker_profiles.DockerClientWrapper", return_value=docker) as wrapper,
    ):
        response = await run_docker_connection_test(
            DockerConnectionTestRequest(docker_host="tcp://arm-worker:2376"),
            _admin=SimpleNamespace(id=1),
        )

    assert response["architecture"] == "aarch64"
    assert response["docker_host"] == "tcp://arm-worker:2376"
    wrapper.assert_called_once()
    assert wrapper.call_args.args[0].host == "tcp://arm-worker:2376"
    assert wrapper.call_args.kwargs == {
        "connect_timeout": 3,
        "operation_timeout": 3,
    }
    docker.close.assert_called_once()


def test_list_worker_profiles_allows_regular_authenticated_user():
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_make_profile(id=3, name="Java Worker")]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=403, detail="Admin access required")
    )
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/api/worker-profiles")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Java Worker"


def test_create_worker_profile_still_rejects_regular_authenticated_user():
    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=403, detail="Admin access required")
    )
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post(
            "/api/worker-profiles",
            json={
                "name": "Java Worker",
                "image": "codify-worker-java:latest",
                "default_execute_run_instruction_template": "Execute {{user_prompt}}",
                "default_plan_run_instruction_template": "Plan {{user_prompt}}",
                "ci_auto_repair_run_instruction_template": "Repair {{issue_title}}",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


@pytest.mark.parametrize(
    ("payload_patch", "expected_field"),
    [
        ({"name": "x" * 101}, "name"),
        ({"image": "x" * 256}, "image"),
        (
            {"environment_variables": [{"key": "X" * 256, "value": "value"}]},
            "environment_variables",
        ),
    ],
)
def test_create_worker_profile_rejects_over_length_fields(payload_patch, expected_field):
    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
        id=1,
        platform_role="platform_admin",
    )
    client = TestClient(app, raise_server_exceptions=False)
    payload = {
        "name": "Java Worker",
        "image": "codify-worker-java:latest",
        "default_execute_run_instruction_template": "Execute {{user_prompt}}",
        "default_plan_run_instruction_template": "Plan {{user_prompt}}",
        "ci_auto_repair_run_instruction_template": "Repair {{issue_title}}",
    }
    payload.update(payload_patch)
    try:
        response = client.post("/api/worker-profiles", json=payload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert expected_field in response.text


def test_disable_default_worker_profile_returns_422():
    profile = _make_profile(id=4, is_default=True)
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.rollback = AsyncMock()

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post("/api/worker-profiles/4/disable")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "Default worker profile cannot be disabled"
