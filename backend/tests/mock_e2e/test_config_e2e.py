"""Mock E2E tests for the Config API endpoints (runtime, integration, aggregated).

Tests the full HTTP request/response cycle through the FastAPI app using a
real in-memory SQLite database.  Only authentication dependencies are mocked
— the actual SQL queries, config validation, persistence, encryption, and
HTTP routing all execute for real.

Endpoints under test:
- GET    /api/config                                   (aggregated)
- PATCH  /api/config                                   (aggregated update)
- POST   /api/config/reset                             (reset all overrides)
- GET    /api/config/runtime                            (runtime section)
- PATCH  /api/config/runtime                            (update runtime)
- DELETE /api/config/runtime/{key}                      (reset single key)
- POST   /api/config/gitlab/test                        (GitLab connectivity)
- POST   /api/config/gitlab/projects/cache/invalidate   (cache invalidation)
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

# Ensure a usable encryption key is available for secret config persistence
os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "test-config-e2e-key-32chars!!!")

from app.database import get_db
from app.dependencies.auth import (
    get_optional_current_user,
    require_admin_user,
    require_authenticated_user,
)
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access_scope,
)
from app.main import app
from app.models import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def _test_engine():
    """In-memory SQLite async engine with all tables created."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_pg_compat(dbapi_conn, connection_record):
        dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda _key: None)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session_factory(_test_engine):
    return async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture()
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture()
def _mock_admin_user():
    user = MagicMock()
    user.id = 1
    user.username = "testadmin"
    user.gitlab_user_id = 100
    user.platform_role = "platform_admin"
    return user


@pytest.fixture()
async def client(session_factory, _mock_admin_user):
    """httpx.AsyncClient wired to the FastAPI app with auth overrides."""

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    access_scope = ProjectAccessScope(
        is_unrestricted=True, accessible_projects=[]
    )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_optional_current_user] = lambda: None
    app.dependency_overrides[require_authenticated_user] = lambda: None
    app.dependency_overrides[require_admin_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_project_access_scope] = lambda: access_scope

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _isolate_runtime_config():
    """Save / restore module-level _runtime_config between tests."""
    from app.config import _runtime_config

    saved = dict(_runtime_config)
    yield
    _runtime_config.clear()
    _runtime_config.update(saved)


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/config/runtime — Read runtime configuration
# ═══════════════════════════════════════════════════════════════════════════


class TestGetRuntimeConfig:
    """GET /api/config/runtime"""

    async def test_returns_default_values_on_fresh_db(self, client: AsyncClient):
        """Fresh DB should return all default runtime config values."""
        resp = await client.get("/api/config/runtime")
        assert resp.status_code == 200
        data = resp.json()
        # Verify expected default values from Settings
        assert data["max_concurrency"] == 3
        assert data["task_timeout"] == 1800
        assert data["scheduler_interval"] == 5
        assert data["default_target_branch"] == "main"
        assert data["max_retries"] == 0
        assert data["retry_delay"] == 60
        assert data["alert_on_failure"] is False
        assert data["slot_max_tasks"] == 0
        assert data["slot_max_tasks_enforce"] is False

    async def test_returns_updated_value_after_patch(self, client: AsyncClient):
        """After PATCH, GET should reflect the new value."""
        await client.patch("/api/config/runtime", json={"max_concurrency": 10})
        resp = await client.get("/api/config/runtime")
        assert resp.status_code == 200
        assert resp.json()["max_concurrency"] == 10

    async def test_secret_keys_show_configured_status(self, client: AsyncClient):
        """Secret keys should be exposed as boolean *_configured flags, not raw values."""
        resp = await client.get("/api/config/runtime")
        data = resp.json()
        # Secret keys are exposed as boolean flags
        assert "anthropic_api_key_configured" in data
        assert "alert_webhook_url_configured" in data
        # Raw secret values must NOT be present
        assert "anthropic_api_key" not in data
        assert "alert_webhook_url" not in data

    async def test_all_expected_keys_present(self, client: AsyncClient):
        """Response should include every field from RuntimeConfigSection."""
        resp = await client.get("/api/config/runtime")
        data = resp.json()
        expected_keys = {
            "max_concurrency", "task_timeout", "scheduler_interval",
            "default_target_branch", "max_retries", "retry_delay",
            "alert_on_failure", "alert_webhook_url_configured",
            "anthropic_base_url", "anthropic_api_key_configured",
            "anthropic_model", "claude_max_turns",
            "allow_monitor_for_users", "allow_schedule_overview_for_users",
            "allow_analytics_for_users", "allow_oidc_diagnostics_for_users",
            "worker_volume_mounts", "maven_cache_host_path",
            "maven_settings_host_path", "slot_max_tasks", "slot_max_tasks_enforce",
        }
        assert expected_keys == set(data.keys())

    async def test_secret_configured_true_after_set(self, client: AsyncClient):
        """After storing a secret key, configured flag should be True."""
        await client.patch("/api/config/runtime", json={"anthropic_api_key": "sk-test-key-12345"})
        resp = await client.get("/api/config/runtime")
        assert resp.status_code == 200
        assert resp.json()["anthropic_api_key_configured"] is True


# ═══════════════════════════════════════════════════════════════════════════
# PATCH /api/config/runtime — Update runtime configuration
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateRuntimeConfig:
    """PATCH /api/config/runtime"""

    async def test_update_max_concurrency(self, client: AsyncClient):
        """Valid max_concurrency update is persisted and returned."""
        resp = await client.patch("/api/config/runtime", json={"max_concurrency": 15})
        assert resp.status_code == 200
        assert resp.json()["max_concurrency"] == 15

    async def test_max_concurrency_below_range(self, client: AsyncClient):
        """max_concurrency below 1 should be rejected."""
        resp = await client.patch("/api/config/runtime", json={"max_concurrency": 0})
        assert resp.status_code == 400
        assert "max_concurrency" in resp.json()["detail"]

    async def test_max_concurrency_above_range(self, client: AsyncClient):
        """max_concurrency above 20 should be rejected."""
        resp = await client.patch("/api/config/runtime", json={"max_concurrency": 21})
        assert resp.status_code == 400

    async def test_update_task_timeout_valid(self, client: AsyncClient):
        """task_timeout within range is accepted."""
        resp = await client.patch("/api/config/runtime", json={"task_timeout": 120})
        assert resp.status_code == 200
        assert resp.json()["task_timeout"] == 120

    async def test_task_timeout_out_of_range(self, client: AsyncClient):
        """task_timeout outside 60-7200 should be rejected."""
        resp = await client.patch("/api/config/runtime", json={"task_timeout": 10})
        assert resp.status_code == 400

        resp2 = await client.patch("/api/config/runtime", json={"task_timeout": 8000})
        assert resp2.status_code == 400

    async def test_update_scheduler_interval(self, client: AsyncClient):
        """scheduler_interval within 1-60 is accepted."""
        resp = await client.patch("/api/config/runtime", json={"scheduler_interval": 30})
        assert resp.status_code == 200
        assert resp.json()["scheduler_interval"] == 30

    async def test_scheduler_interval_out_of_range(self, client: AsyncClient):
        """scheduler_interval outside 1-60 should be rejected."""
        resp = await client.patch("/api/config/runtime", json={"scheduler_interval": 0})
        assert resp.status_code == 400

        resp2 = await client.patch("/api/config/runtime", json={"scheduler_interval": 61})
        assert resp2.status_code == 400

    async def test_update_default_target_branch(self, client: AsyncClient):
        """String value for default_target_branch is persisted."""
        resp = await client.patch("/api/config/runtime", json={"default_target_branch": "develop"})
        assert resp.status_code == 200
        assert resp.json()["default_target_branch"] == "develop"

    async def test_update_anthropic_model(self, client: AsyncClient):
        """String value for anthropic_model is persisted."""
        resp = await client.patch("/api/config/runtime", json={"anthropic_model": "claude-3-opus"})
        assert resp.status_code == 200
        assert resp.json()["anthropic_model"] == "claude-3-opus"

    async def test_update_secret_key_shows_configured(self, client: AsyncClient):
        """Storing a secret key should flip the configured flag to True."""
        resp = await client.patch(
            "/api/config/runtime", json={"anthropic_api_key": "sk-test-secret"}
        )
        assert resp.status_code == 200
        assert resp.json()["anthropic_api_key_configured"] is True

    async def test_clear_flag_with_env_default(self, client: AsyncClient):
        """clear_anthropic_api_key reverts to env default (non-empty → stays configured)."""
        from app.config import get_settings as _gs

        # Set a value via the API
        await client.patch("/api/config/runtime", json={"anthropic_api_key": "sk-to-clear"})
        resp = await client.get("/api/config/runtime")
        assert resp.json()["anthropic_api_key_configured"] is True

        # Ensure a non-empty env default so the clear path can encrypt it
        orig_env = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "env-fallback-key"
        _gs.cache_clear()
        try:
            resp2 = await client.patch(
                "/api/config/runtime", json={"clear_anthropic_api_key": True}
            )
            assert resp2.status_code == 200
            # The override is replaced with the env default; since env
            # default is non-empty the configured flag stays True.
            assert resp2.json()["anthropic_api_key_configured"] is True
        finally:
            if orig_env is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = orig_env
            _gs.cache_clear()

    async def test_clear_flag_empty_env_default_returns_500(self, client: AsyncClient):
        """clear_* flag with an empty env default for a secret key returns 500."""
        # Set a secret value first
        await client.patch("/api/config/runtime", json={"anthropic_api_key": "sk-set"})

        # Now clear it — env default is empty, so encryption of "" fails
        resp = await client.patch(
            "/api/config/runtime", json={"clear_anthropic_api_key": True}
        )
        assert resp.status_code == 500

    async def test_update_multiple_keys_at_once(self, client: AsyncClient):
        """Multiple keys can be updated in a single PATCH request."""
        resp = await client.patch("/api/config/runtime", json={
            "max_concurrency": 8,
            "task_timeout": 3600,
            "default_target_branch": "release",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_concurrency"] == 8
        assert data["task_timeout"] == 3600
        assert data["default_target_branch"] == "release"

    async def test_update_boolean_param(self, client: AsyncClient):
        """Boolean param (alert_on_failure) is persisted correctly."""
        resp = await client.patch("/api/config/runtime", json={"alert_on_failure": True})
        assert resp.status_code == 200
        assert resp.json()["alert_on_failure"] is True

    async def test_update_url_param_valid(self, client: AsyncClient):
        """Valid URL for anthropic_base_url is accepted."""
        resp = await client.patch("/api/config/runtime", json={
            "anthropic_base_url": "https://api.anthropic.com/v1"
        })
        assert resp.status_code == 200
        assert resp.json()["anthropic_base_url"] == "https://api.anthropic.com/v1"

    async def test_update_url_param_invalid(self, client: AsyncClient):
        """Invalid URL for anthropic_base_url should be rejected."""
        resp = await client.patch("/api/config/runtime", json={
            "anthropic_base_url": "not-a-url"
        })
        assert resp.status_code == 400
        assert "valid http/https URL" in resp.json()["detail"]

    async def test_update_slot_max_tasks(self, client: AsyncClient):
        """slot_max_tasks within 0-100 is accepted."""
        resp = await client.patch("/api/config/runtime", json={"slot_max_tasks": 50})
        assert resp.status_code == 200
        assert resp.json()["slot_max_tasks"] == 50

    async def test_slot_max_tasks_out_of_range(self, client: AsyncClient):
        """slot_max_tasks outside 0-100 should be rejected."""
        resp = await client.patch("/api/config/runtime", json={"slot_max_tasks": 101})
        assert resp.status_code == 400

    async def test_empty_body_no_changes(self, client: AsyncClient):
        """PATCH with empty body should not modify any values."""
        get1 = await client.get("/api/config/runtime")
        resp = await client.patch("/api/config/runtime", json={})
        assert resp.status_code == 200
        get2 = await client.get("/api/config/runtime")
        assert get1.json() == get2.json()


# ═══════════════════════════════════════════════════════════════════════════
# DELETE /api/config/runtime/{key} — Reset single runtime config key
# ═══════════════════════════════════════════════════════════════════════════


class TestResetRuntimeConfigKey:
    """DELETE /api/config/runtime/{key}"""

    async def test_reset_reverts_to_default(self, client: AsyncClient):
        """Setting a key then DELETEing it should revert to the default value."""
        await client.patch("/api/config/runtime", json={"max_concurrency": 18})
        resp = await client.get("/api/config/runtime")
        assert resp.json()["max_concurrency"] == 18

        del_resp = await client.delete("/api/config/runtime/max_concurrency")
        assert del_resp.status_code == 200
        assert del_resp.json()["max_concurrency"] == 3  # default

    async def test_reset_unknown_key_returns_404(self, client: AsyncClient):
        """DELETE with an unknown key should return 404."""
        resp = await client.delete("/api/config/runtime/nonexistent_key_xyz")
        assert resp.status_code == 404
        assert "Unknown config key" in resp.json()["detail"]

    async def test_reset_secret_key(self, client: AsyncClient):
        """Resetting a secret key should flip configured status to False."""
        await client.patch("/api/config/runtime", json={"anthropic_api_key": "sk-secret-123"})
        resp = await client.get("/api/config/runtime")
        assert resp.json()["anthropic_api_key_configured"] is True

        del_resp = await client.delete("/api/config/runtime/anthropic_api_key")
        assert del_resp.status_code == 200
        assert del_resp.json()["anthropic_api_key_configured"] is False

    async def test_reset_idempotent(self, client: AsyncClient):
        """Resetting a key that is already at default should succeed silently."""
        resp1 = await client.delete("/api/config/runtime/max_concurrency")
        assert resp1.status_code == 200
        resp2 = await client.delete("/api/config/runtime/max_concurrency")
        assert resp2.status_code == 200
        assert resp1.json()["max_concurrency"] == resp2.json()["max_concurrency"]


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/config — Aggregated configuration
# ═══════════════════════════════════════════════════════════════════════════


class TestGetAggregatedConfig:
    """GET /api/config"""

    async def test_returns_all_sections(self, client: AsyncClient):
        """Response must include runtime, auth, and integration sections."""
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "runtime" in data
        assert "auth" in data
        assert "integration" in data

    async def test_runtime_section_matches_standalone(self, client: AsyncClient):
        """runtime section should match the standalone GET /api/config/runtime."""
        agg_resp = await client.get("/api/config")
        rt_resp = await client.get("/api/config/runtime")
        assert agg_resp.json()["runtime"] == rt_resp.json()

    async def test_auth_section_has_oidc_settings(self, client: AsyncClient):
        """auth section must include OIDC-related fields."""
        resp = await client.get("/api/config")
        auth = resp.json()["auth"]
        assert "oidc_enabled" in auth
        assert "oidc_issuer_url" in auth
        assert "oidc_client_id" in auth
        assert "oidc_redirect_uri" in auth
        assert "oidc_client_secret_configured" in auth

    async def test_integration_section_present(self, client: AsyncClient):
        """integration section must include GitLab settings."""
        resp = await client.get("/api/config")
        integration = resp.json()["integration"]
        assert "gitlab_url" in integration
        assert "gitlab_bot_token_configured" in integration
        assert "gitlab_admin_token_configured" in integration
        assert "gitlab_webhook_secret_configured" in integration


# ═══════════════════════════════════════════════════════════════════════════
# PATCH /api/config — Update aggregated configuration
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateAggregatedConfig:
    """PATCH /api/config"""

    async def test_update_runtime_section(self, client: AsyncClient):
        """PATCH /api/config with runtime section updates runtime values."""
        resp = await client.patch("/api/config", json={
            "runtime": {"max_concurrency": 12}
        })
        assert resp.status_code == 200
        assert resp.json()["runtime"]["max_concurrency"] == 12

    async def test_update_integration_section(self, client: AsyncClient):
        """PATCH /api/config with integration section updates GitLab URL."""
        resp = await client.patch("/api/config", json={
            "integration": {"gitlab_url": "https://gitlab.new.com"}
        })
        assert resp.status_code == 200
        assert resp.json()["integration"]["gitlab_url"] == "https://gitlab.new.com"

    async def test_update_with_clear_flags(self, client: AsyncClient):
        """clear_* flags in runtime section with non-empty env default work correctly."""
        from app.config import get_settings as _gs

        # Set a secret
        await client.patch("/api/config", json={
            "runtime": {"anthropic_api_key": "sk-aggregated-secret"}
        })
        resp = await client.get("/api/config")
        assert resp.json()["runtime"]["anthropic_api_key_configured"] is True

        # Provide a non-empty env default so the clear path can encrypt it
        orig_env = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "env-fallback-for-agg"
        _gs.cache_clear()
        try:
            resp2 = await client.patch("/api/config", json={
                "runtime": {"clear_anthropic_api_key": True}
            })
            assert resp2.status_code == 200
            # Override is replaced with non-empty env default → configured=True
            assert resp2.json()["runtime"]["anthropic_api_key_configured"] is True
        finally:
            if orig_env is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = orig_env
            _gs.cache_clear()

    async def test_empty_body_no_changes(self, client: AsyncClient):
        """PATCH with empty body should return current config without changes."""
        get1 = await client.get("/api/config")
        resp = await client.patch("/api/config", json={})
        assert resp.status_code == 200
        get2 = await client.get("/api/config")
        assert get1.json() == get2.json()

    async def test_update_multiple_sections(self, client: AsyncClient):
        """Multiple sections updated at once."""
        resp = await client.patch("/api/config", json={
            "runtime": {"max_concurrency": 7},
            "integration": {"gitlab_url": "https://gitlab.multi.com"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["runtime"]["max_concurrency"] == 7
        assert data["integration"]["gitlab_url"] == "https://gitlab.multi.com"


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/config/reset — Reset all overrides
# ═══════════════════════════════════════════════════════════════════════════


class TestResetConfig:
    """POST /api/config/reset"""

    async def test_reset_clears_all_overrides(self, client: AsyncClient):
        """After reset, values should revert to defaults."""
        await client.patch("/api/config/runtime", json={
            "max_concurrency": 20,
            "task_timeout": 7200,
        })
        resp = await client.get("/api/config/runtime")
        assert resp.json()["max_concurrency"] == 20

        reset_resp = await client.post("/api/config/reset")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["runtime"]["max_concurrency"] == 3
        assert reset_resp.json()["runtime"]["task_timeout"] == 1800

    async def test_after_reset_runtime_returns_defaults(self, client: AsyncClient):
        """GET /api/config/runtime after reset should show default values."""
        await client.patch("/api/config/runtime", json={"scheduler_interval": 45})
        await client.post("/api/config/reset")
        resp = await client.get("/api/config/runtime")
        assert resp.json()["scheduler_interval"] == 5

    async def test_reset_is_idempotent(self, client: AsyncClient):
        """Resetting when there are no overrides should still succeed."""
        resp1 = await client.post("/api/config/reset")
        assert resp1.status_code == 200
        resp2 = await client.post("/api/config/reset")
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()

    async def test_reset_clears_secret_overrides(self, client: AsyncClient):
        """Reset should also clear any stored secret key overrides."""
        await client.patch("/api/config/runtime", json={"anthropic_api_key": "sk-reset-me"})
        resp = await client.get("/api/config/runtime")
        assert resp.json()["anthropic_api_key_configured"] is True

        await client.post("/api/config/reset")
        resp2 = await client.get("/api/config/runtime")
        assert resp2.json()["anthropic_api_key_configured"] is False


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/config/gitlab/test — Test GitLab connection
# ═══════════════════════════════════════════════════════════════════════════


class TestGitLabConnectionTest:
    """POST /api/config/gitlab/test"""

    async def test_successful_connection(self, client: AsyncClient):
        """Mock a successful GitLab API response → returns server_version and username."""
        mock_gl = MagicMock()
        mock_gl.http_get = MagicMock(side_effect=[
            {"version": "16.8.0"},    # /version
            {"username": "bot-user"},  # /user
        ])

        with patch("app.api.config_integration.GitLabClient") as MockClient:
            instance = MagicMock()
            instance.gl = mock_gl
            instance.close = MagicMock()
            MockClient.return_value = instance

            resp = await client.post("/api/config/gitlab/test", json={
                "integration": {
                    "gitlab_url": "https://gitlab.example.com",
                    "gitlab_bot_token": "glpat-test-token",
                }
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["server_version"] == "16.8.0"
        assert data["username"] == "bot-user"
        assert data["gitlab_url"] == "https://gitlab.example.com"

    async def test_failed_connection(self, client: AsyncClient):
        """Mock a failed GitLab connection → returns error detail."""
        from gitlab.exceptions import GitlabError

        mock_gl = MagicMock()
        mock_gl.http_get = MagicMock(side_effect=GitlabError("Connection refused"))

        with patch("app.api.config_integration.GitLabClient") as MockClient:
            instance = MagicMock()
            instance.gl = mock_gl
            instance.close = MagicMock()
            MockClient.return_value = instance

            resp = await client.post("/api/config/gitlab/test", json={
                "integration": {
                    "gitlab_url": "https://gitlab.example.com",
                    "gitlab_bot_token": "glpat-bad-token",
                }
            })

        assert resp.status_code == 400
        assert "GitLab config test failed" in resp.json()["detail"]

    async def test_with_unsaved_config_values(self, client: AsyncClient):
        """Request body integration values should be used for the test connection."""
        mock_gl = MagicMock()
        mock_gl.http_get = MagicMock(side_effect=[
            {"version": "17.0.0"},
            {"username": "new-bot"},
        ])

        with patch("app.api.config_integration.GitLabClient") as MockClient:
            instance = MagicMock()
            instance.gl = mock_gl
            instance.close = MagicMock()
            MockClient.return_value = instance

            resp = await client.post("/api/config/gitlab/test", json={
                "integration": {
                    "gitlab_url": "https://new-gitlab.example.com",
                    "gitlab_bot_token": "glpat-new-token",
                }
            })

        assert resp.status_code == 200
        # Verify the GitLabClient was constructed with the preview settings
        call_kwargs = MockClient.call_args
        used_settings = call_kwargs.kwargs.get("settings") or call_kwargs[1].get("settings")
        assert used_settings.gitlab_url == "https://new-gitlab.example.com"
        assert used_settings.gitlab_bot_token == "glpat-new-token"

    async def test_missing_bot_token_rejected(self, client: AsyncClient):
        """If bot_token is empty/missing, validation should reject the request."""
        mock_gl = MagicMock()
        mock_gl.http_get = MagicMock(return_value={"version": "16.0.0"})

        with patch("app.api.config_integration.GitLabClient") as MockClient:
            instance = MagicMock()
            instance.gl = mock_gl
            instance.close = MagicMock()
            MockClient.return_value = instance

            resp = await client.post("/api/config/gitlab/test", json={
                "integration": {
                    "gitlab_url": "https://gitlab.example.com",
                    # No bot token — defaults to empty
                }
            })

        assert resp.status_code == 400
        assert "gitlab_bot_token" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/config/gitlab/projects/cache/invalidate — Cache invalidation
# ═══════════════════════════════════════════════════════════════════════════


class TestCacheInvalidation:
    """POST /api/config/gitlab/projects/cache/invalidate"""

    async def test_invalidate_returns_success(self, client: AsyncClient):
        """Cache invalidation endpoint should return a success message."""
        with patch("app.core.gitlab_client.invalidate_project_list_cache") as mock_inv:
            resp = await client.post("/api/config/gitlab/projects/cache/invalidate")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "invalidated" in data["message"].lower()
        mock_inv.assert_called_once()

    async def test_invalidate_calls_cache_function(self, client: AsyncClient):
        """Verify the underlying cache invalidation function is called."""
        with patch("app.core.gitlab_client.invalidate_project_list_cache") as mock_inv:
            await client.post("/api/config/gitlab/projects/cache/invalidate")
            mock_inv.assert_called_once()

    async def test_invalidate_is_idempotent(self, client: AsyncClient):
        """Multiple cache invalidation requests should all succeed."""
        with patch("app.core.gitlab_client.invalidate_project_list_cache"):
            resp1 = await client.post("/api/config/gitlab/projects/cache/invalidate")
            resp2 = await client.post("/api/config/gitlab/projects/cache/invalidate")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
