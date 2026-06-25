from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.worker_profiles import (
    WorkerProfileCreateRequest,
    WorkerProfileEnvironmentVariableRequest,
    create_worker_profile,
    set_default_worker_profile_endpoint,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user, require_authenticated_user
from app.main import app


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
        image="codify-worker:latest",
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
        await create_worker_profile(request, db=db, _current_user=SimpleNamespace(id=1))
    assert exc.value.status_code == 422
    assert "Duplicate worker environment variable key" in str(exc.value.detail)


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
            _current_user=SimpleNamespace(id=1),
        )
    assert exc.value.status_code == 422
    assert "Disabled worker profiles cannot be default" in str(exc.value.detail)


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
