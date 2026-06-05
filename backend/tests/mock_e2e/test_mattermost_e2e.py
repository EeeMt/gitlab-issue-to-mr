"""Mock E2E tests for the Mattermost notification integration.

Part 1 — API endpoints: Tests the full HTTP request/response cycle through
the FastAPI app using a real in-memory SQLite database.  Only authentication
dependencies are mocked — the actual SQL queries, profile validation, config
persistence, and HTTP routing all execute for real.

Part 2 — notify_task_event: Tests the core notification delivery logic using
a real in-memory database for profile/delivery/mapping queries. Only the
MattermostClient HTTP calls are mocked.

Endpoints under test:
- GET    /api/config/notifications
- PATCH  /api/config/notifications/integration
- POST   /api/config/notifications/test
- POST   /api/config/notifications/profiles
- PATCH  /api/config/notifications/profiles/{id}
- DELETE /api/config/notifications/profiles/{id}

Functions under test:
- notify_task_event()
- _resolve_mattermost_user_id()
- _build_attachment_fields()
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# Ensure a usable encryption key is available for secret config persistence
os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "test-mattermost-e2e-key-32chars!")

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
# Valid payload constants
# ---------------------------------------------------------------------------

VALID_CHANNEL_PROFILE = {
    "name": "Eng Channel",
    "enabled": True,
    "target_type": "channel",
    "channel_id": "ch-001",
    "mention_in_channel": True,
    "event_types": ["task_completed", "task_failed"],
    "field_keys": ["task_id", "status"],
}

VALID_DM_PROFILE = {
    "name": "DM Initiator",
    "enabled": True,
    "target_type": "initiator_dm",
    "mention_in_channel": False,
    "event_types": ["task_failed"],
    "field_keys": ["task_id", "error"],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
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


@pytest.fixture
async def session_factory(_test_engine):
    return async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
def _mock_admin_user():
    user = MagicMock()
    user.id = 1
    user.username = "testadmin"
    user.gitlab_user_id = 100
    user.platform_role = "platform_admin"
    return user


@pytest.fixture
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
# GET /api/config/notifications — Read config + profiles
# ═══════════════════════════════════════════════════════════════════════════


class TestGetNotificationConfig:
    """GET /api/config/notifications"""

    async def test_empty_state_returns_defaults(self, client):
        """Fresh DB returns empty profiles and unconfigured integration."""
        resp = await client.get("/api/config/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profiles"] == []
        assert data["integration"]["mattermost_bot_token_configured"] is False

    async def test_returns_created_profiles(self, client):
        """After creating profiles, GET returns them ordered by id."""
        await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        await client.post("/api/config/notifications/profiles", json=VALID_DM_PROFILE)

        resp = await client.get("/api/config/notifications")
        assert resp.status_code == 200
        profiles = resp.json()["profiles"]
        assert len(profiles) == 2
        assert profiles[0]["name"] == "Eng Channel"
        assert profiles[1]["name"] == "DM Initiator"

    async def test_integration_shows_configured_token(self, client):
        """After setting a bot token via API, integration shows token_configured=True."""
        await client.patch(
            "/api/config/notifications/integration",
            json={
                "mattermost_server_url": "https://mm.example.com",
                "mattermost_bot_token": "xoxb-test-token",
            },
        )

        resp = await client.get("/api/config/notifications")
        assert resp.status_code == 200
        integration = resp.json()["integration"]
        assert integration["mattermost_server_url"] == "https://mm.example.com"
        assert integration["mattermost_bot_token_configured"] is True


# ═══════════════════════════════════════════════════════════════════════════
# PATCH /api/config/notifications/integration — Update integration settings
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateIntegration:
    """PATCH /api/config/notifications/integration"""

    async def test_set_server_url(self, client):
        """Setting server_url persists it."""
        resp = await client.patch(
            "/api/config/notifications/integration",
            json={"mattermost_server_url": "https://mm.corp.io"},
        )
        assert resp.status_code == 200
        assert resp.json()["integration"]["mattermost_server_url"] == "https://mm.corp.io"

    async def test_set_bot_token(self, client):
        """Setting bot_token marks token as configured."""
        resp = await client.patch(
            "/api/config/notifications/integration",
            json={"mattermost_bot_token": "bot-secret-123"},
        )
        assert resp.status_code == 200
        assert resp.json()["integration"]["mattermost_bot_token_configured"] is True

    async def test_clear_bot_token(self, client):
        """clear_mattermost_bot_token removes the stored token."""
        # First set a token
        await client.patch(
            "/api/config/notifications/integration",
            json={"mattermost_bot_token": "bot-secret-123"},
        )
        # Then clear it
        resp = await client.patch(
            "/api/config/notifications/integration",
            json={"clear_mattermost_bot_token": True},
        )
        assert resp.status_code == 200
        assert resp.json()["integration"]["mattermost_bot_token_configured"] is False

    async def test_empty_values_are_ignored(self, client):
        """Blank or None values should not overwrite existing settings."""
        await client.patch(
            "/api/config/notifications/integration",
            json={"mattermost_server_url": "https://mm.corp.io"},
        )
        # Sending empty string should not clear it
        resp = await client.patch(
            "/api/config/notifications/integration",
            json={"mattermost_server_url": "  "},
        )
        assert resp.status_code == 200
        # The original value should remain because _normalize_updates skips blank strings
        assert resp.json()["integration"]["mattermost_server_url"] == "https://mm.corp.io"

    async def test_set_url_and_token_together(self, client):
        """Both fields can be set in a single request."""
        resp = await client.patch(
            "/api/config/notifications/integration",
            json={
                "mattermost_server_url": "https://mm.test.io",
                "mattermost_bot_token": "token-xyz",
            },
        )
        assert resp.status_code == 200
        integration = resp.json()["integration"]
        assert integration["mattermost_server_url"] == "https://mm.test.io"
        assert integration["mattermost_bot_token_configured"] is True

    async def test_clear_token_does_not_affect_url(self, client):
        """Clearing the bot token leaves server_url unchanged."""
        await client.patch(
            "/api/config/notifications/integration",
            json={
                "mattermost_server_url": "https://mm.corp.io",
                "mattermost_bot_token": "tok",
            },
        )
        resp = await client.patch(
            "/api/config/notifications/integration",
            json={"clear_mattermost_bot_token": True},
        )
        assert resp.status_code == 200
        integration = resp.json()["integration"]
        assert integration["mattermost_server_url"] == "https://mm.corp.io"
        assert integration["mattermost_bot_token_configured"] is False


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/config/notifications/test — Connection test
# ═══════════════════════════════════════════════════════════════════════════


class TestConnectionTest:
    """POST /api/config/notifications/test"""

    async def test_successful_connection(self, client):
        """A successful Mattermost connection test returns server URL and username."""
        with patch(
            "app.core.mattermost_notifications.test_mattermost_connection",
            new_callable=AsyncMock,
            return_value={"server_url": "https://mm.corp.io", "username": "codify-bot"},
        ):
            resp = await client.post(
                "/api/config/notifications/test",
                json={"integration": {"mattermost_server_url": "https://mm.corp.io", "mattermost_bot_token": "tok"}},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["server_url"] == "https://mm.corp.io"
        assert data["username"] == "codify-bot"

    async def test_connection_failure_returns_400(self, client):
        """Mattermost connectivity failure is reported as 400."""
        from app.core.mattermost_notifications import MattermostNotificationError

        with patch(
            "app.core.mattermost_notifications.test_mattermost_connection",
            new_callable=AsyncMock,
            side_effect=MattermostNotificationError("Connection refused"),
        ):
            resp = await client.post(
                "/api/config/notifications/test",
                json={"integration": {"mattermost_server_url": "https://bad.host", "mattermost_bot_token": "tok"}},
            )
        assert resp.status_code == 400
        assert "Connection refused" in resp.json()["detail"]

    async def test_connection_httpx_error_returns_400(self, client):
        """httpx transport errors are caught and returned as 400."""
        import httpx

        with patch(
            "app.core.mattermost_notifications.test_mattermost_connection",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("DNS resolution failed"),
        ):
            resp = await client.post(
                "/api/config/notifications/test",
                json={"integration": {"mattermost_server_url": "https://no-dns.local", "mattermost_bot_token": "tok"}},
            )
        assert resp.status_code == 400
        assert "DNS resolution failed" in resp.json()["detail"]

    async def test_connection_uses_stored_token_when_not_provided(self, client):
        """When bot_token is not in the request, the stored token is used."""
        # Save a bot token via the API so it's in the DB
        await client.patch(
            "/api/config/notifications/integration",
            json={"mattermost_bot_token": "stored-token"},
        )

        captured = {}

        async def _mock_test(*, server_url, bot_token):
            captured["bot_token"] = bot_token
            return {"server_url": server_url, "username": "bot"}

        with patch("app.core.mattermost_notifications.test_mattermost_connection", side_effect=_mock_test):
            resp = await client.post(
                "/api/config/notifications/test",
                json={"integration": {"mattermost_server_url": "https://mm.io"}},
            )
        assert resp.status_code == 200
        assert captured["bot_token"] == "stored-token"

    async def test_connection_clear_token_sends_empty(self, client):
        """clear_mattermost_bot_token causes an empty token to be tested."""
        # Save a bot token via the API so it's in the DB
        await client.patch(
            "/api/config/notifications/integration",
            json={"mattermost_bot_token": "stored-token"},
        )

        captured = {}

        async def _mock_test(*, server_url, bot_token):
            captured["bot_token"] = bot_token
            return {"server_url": server_url, "username": "bot"}

        with patch("app.core.mattermost_notifications.test_mattermost_connection", side_effect=_mock_test):
            resp = await client.post(
                "/api/config/notifications/test",
                json={"integration": {"clear_mattermost_bot_token": True, "mattermost_server_url": "https://mm.io"}},
            )
        assert resp.status_code == 200
        assert captured["bot_token"] == ""


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/config/notifications/profiles — Create profile
# ═══════════════════════════════════════════════════════════════════════════


class TestCreateProfile:
    """POST /api/config/notifications/profiles"""

    async def test_create_channel_profile(self, client):
        """Creating a channel profile returns the full profile with id."""
        resp = await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] >= 1
        assert data["name"] == "Eng Channel"
        assert data["target_type"] == "channel"
        assert data["channel_id"] == "ch-001"
        assert data["mention_in_channel"] is True
        assert "send_for_manual_tasks" not in data
        assert set(data["event_types"]) == {"task_completed", "task_failed"}
        assert set(data["field_keys"]) == {"task_id", "status"}
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_dm_profile(self, client):
        """Creating a DM profile auto-clears team/channel/mention fields."""
        resp = await client.post("/api/config/notifications/profiles", json=VALID_DM_PROFILE)
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_type"] == "initiator_dm"
        assert data["channel_id"] is None
        assert data["mention_in_channel"] is False
        assert "send_for_manual_tasks" not in data

    async def test_create_dm_profile_strips_channel_id(self, client):
        """Even if channel_id is provided for DM, it is cleared."""
        payload = {
            **VALID_DM_PROFILE,
            "channel_id": "should-be-cleared",
            "mention_in_channel": True,
        }
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["channel_id"] is None
        assert data["mention_in_channel"] is False

    async def test_create_profile_all_event_types(self, client):
        """A profile can subscribe to all known event types."""
        all_events = [
            "task_completed", "task_failed", "task_rescheduled",
            "task_execute_now", "task_retry_scheduled", "task_cancelled",
        ]
        payload = {**VALID_CHANNEL_PROFILE, "event_types": all_events}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        assert set(resp.json()["event_types"]) == set(all_events)

    async def test_create_profile_all_field_keys(self, client):
        """A profile can include all known field keys."""
        all_fields = [
            "task_id", "project", "issue", "merge_request", "initiator",
            "status", "branch", "target_branch", "scheduled_at",
            "schedule_change", "error", "task_link",
        ]
        payload = {**VALID_CHANNEL_PROFILE, "field_keys": all_fields}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        assert set(resp.json()["field_keys"]) == set(all_fields)

    async def test_create_multiple_profiles(self, client):
        """Multiple profiles can coexist."""
        r1 = await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        r2 = await client.post("/api/config/notifications/profiles", json=VALID_DM_PROFILE)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] != r2.json()["id"]

    async def test_duplicate_names_allowed(self, client):
        """Two profiles with the same name are allowed."""
        await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        resp = await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        assert resp.status_code == 200

    async def test_create_profile_name_whitespace_trimmed(self, client):
        """Leading/trailing whitespace in name is trimmed."""
        payload = {**VALID_CHANNEL_PROFILE, "name": "  Trimmed Name  "}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Trimmed Name"

    async def test_disabled_profile_created(self, client):
        """A profile can be created in disabled state."""
        payload = {**VALID_CHANNEL_PROFILE, "enabled": False}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    # --- Validation errors ---

    async def test_empty_name_rejected(self, client):
        """Empty profile name is rejected with 422."""
        payload = {**VALID_CHANNEL_PROFILE, "name": ""}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 422

    async def test_whitespace_only_name_rejected(self, client):
        """Whitespace-only name is rejected."""
        payload = {**VALID_CHANNEL_PROFILE, "name": "   "}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 422

    async def test_invalid_target_type_rejected(self, client):
        """Unknown target_type is rejected."""
        payload = {**VALID_CHANNEL_PROFILE, "target_type": "email"}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 422

    async def test_empty_event_types_rejected(self, client):
        """At least one event type must be selected."""
        payload = {**VALID_CHANNEL_PROFILE, "event_types": []}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 422

    async def test_empty_field_keys_rejected(self, client):
        """At least one field key must be selected."""
        payload = {**VALID_CHANNEL_PROFILE, "field_keys": []}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 422

    async def test_channel_without_channel_id_rejected(self, client):
        """Channel profile without channel_id is rejected."""
        payload = {**VALID_CHANNEL_PROFILE, "channel_id": None}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 422

    async def test_channel_with_empty_channel_id_rejected(self, client):
        """Channel profile with empty channel_id is rejected."""
        payload = {**VALID_CHANNEL_PROFILE, "channel_id": "  "}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 422

    async def test_invalid_event_types_filtered(self, client):
        """Unknown event types are filtered out; if none remain, rejected."""
        payload = {**VALID_CHANNEL_PROFILE, "event_types": ["bogus_event"]}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 422

    async def test_invalid_field_keys_filtered(self, client):
        """Unknown field keys are filtered out; if none remain, rejected."""
        payload = {**VALID_CHANNEL_PROFILE, "field_keys": ["nonexistent_field"]}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 422

    async def test_mixed_valid_invalid_event_types_keeps_valid(self, client):
        """Valid event types survive alongside invalid ones."""
        payload = {
            **VALID_CHANNEL_PROFILE,
            "event_types": ["task_completed", "bogus", "task_failed"],
        }
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        assert set(resp.json()["event_types"]) == {"task_completed", "task_failed"}

    async def test_mixed_valid_invalid_field_keys_keeps_valid(self, client):
        """Valid field keys survive alongside invalid ones."""
        payload = {
            **VALID_CHANNEL_PROFILE,
            "field_keys": ["task_id", "nonexistent", "status"],
        }
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        assert set(resp.json()["field_keys"]) == {"task_id", "status"}

    async def test_duplicate_event_types_deduplicated(self, client):
        """Duplicate event types are deduplicated."""
        payload = {
            **VALID_CHANNEL_PROFILE,
            "event_types": ["task_completed", "task_completed", "task_failed"],
        }
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        assert resp.json()["event_types"] == ["task_completed", "task_failed"]

    async def test_duplicate_field_keys_deduplicated(self, client):
        """Duplicate field keys are deduplicated."""
        payload = {
            **VALID_CHANNEL_PROFILE,
            "field_keys": ["task_id", "task_id", "status"],
        }
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        assert resp.json()["field_keys"] == ["task_id", "status"]


# ═══════════════════════════════════════════════════════════════════════════
# PATCH /api/config/notifications/profiles/{id} — Update profile
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateProfile:
    """PATCH /api/config/notifications/profiles/{id}"""

    async def _create_profile(self, client, payload=None):
        payload = payload or VALID_CHANNEL_PROFILE
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        return resp.json()

    async def test_update_name(self, client):
        """Profile name can be updated."""
        profile = await self._create_profile(client)
        updated = {**VALID_CHANNEL_PROFILE, "name": "New Name"}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_update_toggle_enabled(self, client):
        """Profile can be enabled/disabled."""
        profile = await self._create_profile(client)
        updated = {**VALID_CHANNEL_PROFILE, "enabled": False}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    async def test_update_change_target_type_channel_to_dm(self, client):
        """Switching from channel to DM clears team/channel fields."""
        profile = await self._create_profile(client)
        updated = {**VALID_DM_PROFILE, "name": profile["name"]}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_type"] == "initiator_dm"
        assert data["channel_id"] is None
        assert data["mention_in_channel"] is False

    async def test_update_change_target_type_dm_to_channel(self, client):
        """Switching from DM to channel succeeds when channel_id is provided."""
        profile = await self._create_profile(client, VALID_DM_PROFILE)
        updated = {**VALID_CHANNEL_PROFILE}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 200
        assert resp.json()["target_type"] == "channel"
        assert resp.json()["channel_id"] == "ch-001"

    async def test_update_event_types(self, client):
        """Event types can be changed on update."""
        profile = await self._create_profile(client)
        updated = {**VALID_CHANNEL_PROFILE, "event_types": ["task_cancelled"]}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 200
        assert resp.json()["event_types"] == ["task_cancelled"]

    async def test_update_field_keys(self, client):
        """Field keys can be changed on update."""
        profile = await self._create_profile(client)
        updated = {**VALID_CHANNEL_PROFILE, "field_keys": ["project", "issue", "task_link"]}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 200
        assert set(resp.json()["field_keys"]) == {"project", "issue", "task_link"}

    async def test_update_response_omits_deprecated_manual_flag(self, client):
        """The deprecated manual-task flag is no longer returned by the API."""
        profile = await self._create_profile(client)
        updated = {**VALID_CHANNEL_PROFILE, "mention_in_channel": False}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 200
        assert "send_for_manual_tasks" not in resp.json()

    async def test_update_mention_in_channel(self, client):
        """mention_in_channel can be toggled."""
        profile = await self._create_profile(client)
        updated = {**VALID_CHANNEL_PROFILE, "mention_in_channel": False}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 200
        assert resp.json()["mention_in_channel"] is False

    async def test_update_nonexistent_profile_returns_404(self, client):
        """Updating a profile that doesn't exist returns 404."""
        resp = await client.patch(
            "/api/config/notifications/profiles/99999",
            json=VALID_CHANNEL_PROFILE,
        )
        assert resp.status_code == 404
        assert "99999" in resp.json()["detail"]

    async def test_update_preserves_id(self, client):
        """After update, the profile ID remains unchanged."""
        profile = await self._create_profile(client)
        updated = {**VALID_CHANNEL_PROFILE, "name": "Renamed"}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == profile["id"]

    # --- Validation on update ---

    async def test_update_empty_name_rejected(self, client):
        """Empty name on update is rejected."""
        profile = await self._create_profile(client)
        updated = {**VALID_CHANNEL_PROFILE, "name": ""}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 422

    async def test_update_invalid_target_type_rejected(self, client):
        """Invalid target_type on update is rejected."""
        profile = await self._create_profile(client)
        updated = {**VALID_CHANNEL_PROFILE, "target_type": "sms"}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 422

    async def test_update_empty_event_types_rejected(self, client):
        """Empty event_types on update is rejected."""
        profile = await self._create_profile(client)
        updated = {**VALID_CHANNEL_PROFILE, "event_types": []}
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 422

    async def test_update_channel_missing_channel_id_rejected(self, client):
        """Switching to channel without channel_id on update is rejected."""
        profile = await self._create_profile(client, VALID_DM_PROFILE)
        updated = {
            **VALID_CHANNEL_PROFILE,
            "channel_id": None,
        }
        resp = await client.patch(
            f"/api/config/notifications/profiles/{profile['id']}", json=updated
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# DELETE /api/config/notifications/profiles/{id} — Delete profile
# ═══════════════════════════════════════════════════════════════════════════


class TestDeleteProfile:
    """DELETE /api/config/notifications/profiles/{id}"""

    async def test_delete_existing_profile(self, client):
        """Deleting an existing profile returns success."""
        resp = await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        profile_id = resp.json()["id"]

        resp = await client.delete(f"/api/config/notifications/profiles/{profile_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        # Verify gone
        listing = await client.get("/api/config/notifications")
        assert len(listing.json()["profiles"]) == 0

    async def test_delete_nonexistent_profile_returns_404(self, client):
        """Deleting a profile that doesn't exist returns 404."""
        resp = await client.delete("/api/config/notifications/profiles/99999")
        assert resp.status_code == 404
        assert "99999" in resp.json()["detail"]

    async def test_delete_one_of_many(self, client):
        """Deleting one profile leaves the others intact."""
        r1 = await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        r2 = await client.post("/api/config/notifications/profiles", json=VALID_DM_PROFILE)
        id1 = r1.json()["id"]
        id2 = r2.json()["id"]

        await client.delete(f"/api/config/notifications/profiles/{id1}")
        listing = await client.get("/api/config/notifications")
        profiles = listing.json()["profiles"]
        assert len(profiles) == 1
        assert profiles[0]["id"] == id2

    async def test_delete_then_recreate(self, client):
        """After deleting, creating a new profile works and the profile is usable."""
        resp = await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        old_id = resp.json()["id"]
        await client.delete(f"/api/config/notifications/profiles/{old_id}")

        resp = await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        assert resp.status_code == 200
        new_profile = resp.json()
        assert new_profile["name"] == VALID_CHANNEL_PROFILE["name"]
        # Verify the new profile is listed
        listing = await client.get("/api/config/notifications")
        assert len(listing.json()["profiles"]) == 1

    async def test_double_delete_returns_404(self, client):
        """Deleting the same profile twice returns 404 the second time."""
        resp = await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        profile_id = resp.json()["id"]
        resp1 = await client.delete(f"/api/config/notifications/profiles/{profile_id}")
        assert resp1.status_code == 200
        resp2 = await client.delete(f"/api/config/notifications/profiles/{profile_id}")
        assert resp2.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Full CRUD lifecycle
# ═══════════════════════════════════════════════════════════════════════════


class TestFullCRUDLifecycle:
    """Verify the complete create → read → update → delete flow."""

    async def test_channel_profile_lifecycle(self, client):
        """Channel profile: create → read → update → delete."""
        # Create
        resp = await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        assert resp.status_code == 200
        profile = resp.json()
        pid = profile["id"]

        # Read
        resp = await client.get("/api/config/notifications")
        assert resp.status_code == 200
        profiles = resp.json()["profiles"]
        assert len(profiles) == 1
        assert profiles[0]["id"] == pid

        # Update
        updated_payload = {
            **VALID_CHANNEL_PROFILE,
            "name": "Updated Name",
            "event_types": ["task_rescheduled", "task_execute_now"],
            "field_keys": ["task_id", "scheduled_at", "schedule_change"],
            "mention_in_channel": False,
        }
        resp = await client.patch(f"/api/config/notifications/profiles/{pid}", json=updated_payload)
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["name"] == "Updated Name"
        assert set(updated["event_types"]) == {"task_rescheduled", "task_execute_now"}
        assert updated["mention_in_channel"] is False

        # Delete
        resp = await client.delete(f"/api/config/notifications/profiles/{pid}")
        assert resp.status_code == 200

        # Verify empty
        resp = await client.get("/api/config/notifications")
        assert resp.json()["profiles"] == []

    async def test_dm_profile_lifecycle(self, client):
        """DM profile: create → update to channel → delete."""
        # Create as DM
        resp = await client.post("/api/config/notifications/profiles", json=VALID_DM_PROFILE)
        assert resp.status_code == 200
        pid = resp.json()["id"]
        assert resp.json()["target_type"] == "initiator_dm"

        # Update to channel
        resp = await client.patch(
            f"/api/config/notifications/profiles/{pid}", json=VALID_CHANNEL_PROFILE
        )
        assert resp.status_code == 200
        assert resp.json()["target_type"] == "channel"
        assert resp.json()["channel_id"] == "ch-001"

        # Delete
        resp = await client.delete(f"/api/config/notifications/profiles/{pid}")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases — target_type semantics
# ═══════════════════════════════════════════════════════════════════════════


class TestTargetTypeSemantics:
    """Verify target_type-specific field behavior."""

    async def test_channel_with_whitespace_channel_id(self, client):
        """Whitespace-only channel_id for channel is rejected."""
        payload = {**VALID_CHANNEL_PROFILE, "channel_id": "   "}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 422

    async def test_dm_ignores_mention_in_channel(self, client):
        """For DM profiles, mention_in_channel is forced False."""
        payload = {**VALID_DM_PROFILE, "mention_in_channel": True}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        assert resp.json()["mention_in_channel"] is False

    async def test_target_type_trimmed(self, client):
        """Target type is trimmed of whitespace."""
        payload = {**VALID_CHANNEL_PROFILE, "target_type": "  channel  "}
        resp = await client.post("/api/config/notifications/profiles", json=payload)
        assert resp.status_code == 200
        assert resp.json()["target_type"] == "channel"


# ═══════════════════════════════════════════════════════════════════════════
# Integration + profiles combined scenario
# ═══════════════════════════════════════════════════════════════════════════


class TestIntegrationAndProfilesCombined:
    """Verify that integration settings and profiles are independent."""

    async def test_integration_update_does_not_affect_profiles(self, client):
        """Updating integration settings doesn't touch profiles."""
        await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        await client.patch(
            "/api/config/notifications/integration",
            json={"mattermost_server_url": "https://new-mm.io"},
        )
        resp = await client.get("/api/config/notifications")
        assert len(resp.json()["profiles"]) == 1
        assert resp.json()["integration"]["mattermost_server_url"] == "https://new-mm.io"

    async def test_integration_update_response_includes_profiles(self, client):
        """PATCH integration returns full config including profiles."""
        await client.post("/api/config/notifications/profiles", json=VALID_CHANNEL_PROFILE)
        resp = await client.patch(
            "/api/config/notifications/integration",
            json={"mattermost_server_url": "https://mm.io"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["profiles"]) == 1

    async def test_multiple_profiles_ordering(self, client):
        """Profiles are returned ordered by ascending ID."""
        names = ["Zulu", "Alpha", "Mike"]
        ids = []
        for name in names:
            r = await client.post(
                "/api/config/notifications/profiles",
                json={**VALID_CHANNEL_PROFILE, "name": name},
            )
            ids.append(r.json()["id"])

        resp = await client.get("/api/config/notifications")
        profiles = resp.json()["profiles"]
        assert [p["id"] for p in profiles] == sorted(ids)
        assert [p["name"] for p in profiles] == names


# ═══════════════════════════════════════════════════════════════════════════
# Part 2 — notify_task_event core logic
# ═══════════════════════════════════════════════════════════════════════════
#
# These tests exercise the notification delivery pipeline directly.
# The real in-memory SQLite database is used for profile/delivery/mapping
# queries.  Only the MattermostClient HTTP calls are mocked.
# ═══════════════════════════════════════════════════════════════════════════

from types import SimpleNamespace

from sqlalchemy import select

from app.core.mattermost_notifications import (
    MATTERMOST_EVENT_TASK_CANCELLED,
    MATTERMOST_EVENT_TASK_COMPLETED,
    MATTERMOST_EVENT_TASK_FAILED,
    MATTERMOST_EVENT_TASK_RESCHEDULED,
    MattermostNotificationError,
    notify_task_event,
)
from app.models import (
    Issue,
    MattermostNotificationDelivery,
    MattermostNotificationProfile,
    MattermostUserMapping,
    Task,
    TaskStatus,
)


def _mock_settings(**overrides):
    """Return a mock settings object with Mattermost integration configured."""
    defaults = {
        "mattermost_server_url": "https://mm.test.io",
        "mattermost_bot_token": "test-bot-token",
        "dashboard_url": "https://dashboard.test.io",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
async def notify_engine():
    """Dedicated in-memory SQLite engine for notify_task_event tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _compat(dbapi_conn, connection_record):
        dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda _key: None)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def notify_sf(notify_engine):
    return async_sessionmaker(
        notify_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
async def notify_session(notify_sf):
    async with notify_sf() as session:
        yield session


async def _seed_profile(session, *, name="default", enabled=True, target_type="channel",
                        team_name="eng", channel_name="alerts", channel_id="ch-seeded",
                        mention=False, events=None, fields=None):
    """Insert a MattermostNotificationProfile into the test DB."""
    import json
    profile = MattermostNotificationProfile(
        name=name,
        enabled=enabled,
        target_type=target_type,
        channel_id=channel_id if target_type == "channel" else None,
        mention_in_channel=mention,
        event_types_json=json.dumps(events or ["task_completed", "task_failed"]),
        field_keys_json=json.dumps(fields or ["task_id", "status"]),
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def _seed_issue(session, *, issue_id=None, project_id=10, **kwargs):
    """Insert an Issue into the test DB."""
    defaults = dict(
        title="Test issue",
        description="Test description",
        branch_name="feature/test",
        target_branch="main",
        status="open",
        project_id=project_id,
    )
    defaults.update(kwargs)
    if issue_id is not None:
        defaults["id"] = issue_id
    issue = Issue(**defaults)
    session.add(issue)
    await session.commit()
    await session.refresh(issue)
    return issue


async def _seed_task(session, *, task_id=None, status=TaskStatus.COMPLETED,
                     initiator_username="alice", initiator_user_id=None,
                     initiator_gitlab_user_id=None, project_id=10,
                     issue=None, error_message=None, **kwargs):
    """Insert a Task into the test DB."""
    if issue is None:
        issue = await _seed_issue(session, project_id=project_id)

    defaults = dict(
        project_id=project_id,
        issue_id=issue.id,
        user_prompt="test prompt",
        status=status,
        initiator_username=initiator_username,
        initiator_user_id=initiator_user_id,
        initiator_gitlab_user_id=initiator_gitlab_user_id,
        error_message=error_message,
    )
    defaults.update(kwargs)
    if task_id is not None:
        defaults["id"] = task_id
    task = Task(**defaults)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    # Eagerly load the issue relationship to avoid lazy loading issues
    task.issue = issue
    return task


async def _seed_user_mapping(session, *, gitlab_username="alice", mattermost_user_id="mm-alice-id",
                             mattermost_username="alice.mm", user_id=None, gitlab_user_id=None):
    """Insert a MattermostUserMapping into the test DB."""
    mapping = MattermostUserMapping(
        user_id=user_id,
        gitlab_user_id=gitlab_user_id,
        gitlab_username=gitlab_username,
        mattermost_user_id=mattermost_user_id,
        mattermost_username=mattermost_username,
        source="username",
    )
    session.add(mapping)
    await session.commit()
    return mapping


async def _get_deliveries(session, task_id: int) -> list[MattermostNotificationDelivery]:
    result = await session.execute(
        select(MattermostNotificationDelivery)
        .where(MattermostNotificationDelivery.task_id == task_id)
        .order_by(MattermostNotificationDelivery.id.asc())
    )
    return list(result.scalars().all())


def _patches(notify_sf, mock_client, **settings_overrides):
    """Return a combined context-manager patching AsyncSessionLocal, MattermostClient, and settings."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        with patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            notify_sf,
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=_mock_settings(**settings_overrides),
        ):
            yield
    return _ctx()


# ---------------------------------------------------------------------------
# notify_task_event — channel notifications
# ---------------------------------------------------------------------------


class TestNotifyChannelNotification:
    """notify_task_event with channel-type profiles."""

    async def test_posts_to_channel_and_records_delivery(self, notify_sf, notify_session):
        """A matching channel profile triggers a post and success delivery record."""
        profile = await _seed_profile(notify_session, events=["task_completed"])
        task = await _seed_task(notify_session)

        mock_client = AsyncMock()

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.get_channel_by_name.assert_not_called()
        mock_client.create_post.assert_awaited_once()
        post_args = mock_client.create_post.await_args
        assert post_args.args[0] == "ch-seeded"

        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 1
        assert deliveries[0].status == "success"
        assert deliveries[0].profile_id == profile.id

    async def test_mention_in_channel(self, notify_sf, notify_session):
        """With mention_in_channel=True, the message includes @username."""
        await _seed_profile(notify_session, mention=True, events=["task_completed"])
        task = await _seed_task(notify_session, initiator_username="bob")

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        message = mock_client.create_post.await_args.args[1]
        assert message.startswith("@bob ")

    async def test_no_mention_when_disabled(self, notify_sf, notify_session):
        """With mention_in_channel=False, the message has no @mention."""
        await _seed_profile(notify_session, mention=False, events=["task_completed"])
        task = await _seed_task(notify_session, initiator_username="bob")

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        message = mock_client.create_post.await_args.args[1]
        assert not message.startswith("@bob")

    async def test_no_mention_when_no_initiator(self, notify_sf, notify_session):
        """With mention=True but no initiator, no @mention is added."""
        await _seed_profile(notify_session, mention=True, events=["task_completed"])
        task = await _seed_task(notify_session, initiator_username=None)

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        message = mock_client.create_post.await_args.args[1]
        assert not message.startswith("@")

    async def test_post_includes_attachments_and_card(self, notify_sf, notify_session):
        """The post props contain attachments and card markdown."""
        await _seed_profile(notify_session, events=["task_failed"],
                            fields=["task_id", "status", "error"])
        task = await _seed_task(notify_session, status=TaskStatus.FAILED,
                                error_message="Container OOM killed")

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)

        props = mock_client.create_post.await_args.args[2]
        assert "attachments" in props
        assert len(props["attachments"]) == 1
        assert props["attachments"][0]["color"] == "danger"
        assert "card" in props
        assert "OOM killed" in props["card"]

    async def test_channel_api_failure_records_failed_delivery(self, notify_sf, notify_session):
        """If Mattermost API fails, a 'failed' delivery record is created."""
        await _seed_profile(notify_session, events=["task_completed"])
        task = await _seed_task(notify_session)

        mock_client = AsyncMock()
        mock_client.create_post.side_effect = MattermostNotificationError("channel not found")

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 1
        assert deliveries[0].status == "failed"
        assert "channel not found" in deliveries[0].error_message


# ---------------------------------------------------------------------------
# notify_task_event — DM notifications
# ---------------------------------------------------------------------------


class TestNotifyDMNotification:
    """notify_task_event with DM-type profiles."""

    async def test_dm_with_existing_user_mapping(self, notify_sf, notify_session):
        """When a MattermostUserMapping exists, it's used without API lookup."""
        await _seed_profile(notify_session, target_type="initiator_dm",
                            events=["task_completed"])
        task = await _seed_task(notify_session, initiator_username="alice")
        await _seed_user_mapping(notify_session, gitlab_username="alice",
                                 mattermost_user_id="mm-alice-123")

        mock_client = AsyncMock()
        mock_client.create_direct_channel.return_value = {"id": "dm-ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        # Should NOT call get_user_by_username since mapping exists
        mock_client.get_user_by_username.assert_not_awaited()
        mock_client.create_direct_channel.assert_awaited_once_with("mm-alice-123")
        mock_client.create_post.assert_awaited_once()

        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 1
        assert deliveries[0].status == "success"

    async def test_dm_creates_mapping_on_first_lookup(self, notify_sf, notify_session):
        """When no mapping exists, username lookup creates one."""
        await _seed_profile(notify_session, target_type="initiator_dm",
                            events=["task_completed"])
        task = await _seed_task(notify_session, initiator_username="bob")

        mock_client = AsyncMock()
        mock_client.get_user_by_username.return_value = {"id": "mm-bob-456", "username": "bob.mm"}
        mock_client.create_direct_channel.return_value = {"id": "dm-ch-002"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.get_user_by_username.assert_awaited_once_with("bob")
        mock_client.create_direct_channel.assert_awaited_once_with("mm-bob-456")

        # Verify mapping was persisted
        result = await notify_session.execute(
            select(MattermostUserMapping).where(MattermostUserMapping.gitlab_username == "bob")
        )
        mapping = result.scalars().first()
        assert mapping is not None
        assert mapping.mattermost_user_id == "mm-bob-456"
        assert mapping.mattermost_username == "bob.mm"

    async def test_dm_skipped_when_no_initiator(self, notify_sf, notify_session):
        """DM notification is skipped with 'skipped' status when initiator is missing."""
        await _seed_profile(notify_session, target_type="initiator_dm",
                            events=["task_failed"])
        task = await _seed_task(notify_session, status=TaskStatus.FAILED,
                                initiator_username=None)

        mock_client = AsyncMock()

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)

        mock_client.create_direct_channel.assert_not_called()
        mock_client.create_post.assert_not_called()

        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 1
        assert deliveries[0].status == "skipped"
        assert "No Mattermost user" in deliveries[0].error_message

    async def test_dm_skipped_when_username_lookup_returns_empty_id(self, notify_sf, notify_session):
        """If Mattermost user lookup returns empty ID, DM is skipped."""
        await _seed_profile(notify_session, target_type="initiator_dm",
                            events=["task_completed"])
        task = await _seed_task(notify_session, initiator_username="ghost")

        mock_client = AsyncMock()
        mock_client.get_user_by_username.return_value = {"id": "", "username": "ghost"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 1
        assert deliveries[0].status == "skipped"

    async def test_dm_api_failure_records_failed_delivery(self, notify_sf, notify_session):
        """If Mattermost DM fails, a 'failed' delivery record is created."""
        await _seed_profile(notify_session, target_type="initiator_dm",
                            events=["task_completed"])
        task = await _seed_task(notify_session, initiator_username="alice")
        await _seed_user_mapping(notify_session)

        mock_client = AsyncMock()
        mock_client.create_direct_channel.side_effect = MattermostNotificationError("user not found")

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 1
        assert deliveries[0].status == "failed"
        assert "user not found" in deliveries[0].error_message


# ---------------------------------------------------------------------------
# notify_task_event — filtering and early returns
# ---------------------------------------------------------------------------


class TestNotifyFiltering:
    """Event type filtering, manual task filtering, and early returns."""

    async def test_skips_disabled_profile(self, notify_sf, notify_session):
        """Disabled profiles are not queried at all."""
        await _seed_profile(notify_session, enabled=False, events=["task_completed"])
        task = await _seed_task(notify_session)

        mock_client = AsyncMock()

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.get_channel_by_name.assert_not_called()
        mock_client.create_post.assert_not_called()
        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 0

    async def test_skips_non_matching_event_type(self, notify_sf, notify_session):
        """A profile that doesn't subscribe to the event type is skipped."""
        await _seed_profile(notify_session, events=["task_completed"])
        task = await _seed_task(notify_session, status=TaskStatus.FAILED)

        mock_client = AsyncMock()

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)

        mock_client.create_post.assert_not_called()
        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 0

    async def test_no_profiles_does_nothing(self, notify_sf, notify_session):
        """When no profiles exist, nothing happens."""
        task = await _seed_task(notify_session)

        mock_client = AsyncMock()

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.create_post.assert_not_called()

    async def test_empty_server_url_returns_early(self, notify_sf, notify_session):
        """Empty mattermost_server_url causes early return without DB queries."""
        await _seed_profile(notify_session, events=["task_completed"])
        task = await _seed_task(notify_session)

        mock_client = AsyncMock()

        with _patches(notify_sf, mock_client, mattermost_server_url=""):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.create_post.assert_not_called()

    async def test_empty_bot_token_returns_early(self, notify_sf, notify_session):
        """Empty mattermost_bot_token causes early return."""
        await _seed_profile(notify_session, events=["task_completed"])
        task = await _seed_task(notify_session)

        mock_client = AsyncMock()

        with _patches(notify_sf, mock_client, mattermost_bot_token=""):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.create_post.assert_not_called()

    async def test_invalid_event_type_raises_value_error(self, notify_sf, notify_session):
        """An unsupported event type raises ValueError immediately."""
        task = await _seed_task(notify_session)

        with pytest.raises(ValueError, match="Unsupported Mattermost event type"):
            await notify_task_event(task, "invalid_event_type")


# ---------------------------------------------------------------------------
# notify_task_event — multiple profiles
# ---------------------------------------------------------------------------


class TestNotifyMultipleProfiles:
    """Verify behavior when multiple profiles exist."""

    async def test_multiple_matching_profiles(self, notify_sf, notify_session):
        """Each matching profile results in its own delivery record."""
        p1 = await _seed_profile(notify_session, name="P1", events=["task_completed"])
        p2 = await _seed_profile(notify_session, name="P2", events=["task_completed"])
        task = await _seed_task(notify_session)

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        assert mock_client.create_post.await_count == 2
        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 2
        assert {d.profile_id for d in deliveries} == {p1.id, p2.id}
        assert all(d.status == "success" for d in deliveries)

    async def test_mixed_match_and_skip(self, notify_sf, notify_session):
        """Only profiles matching the event type get notifications."""
        p_match = await _seed_profile(notify_session, name="Match",
                                      events=["task_completed"])
        await _seed_profile(notify_session, name="Skip",
                            events=["task_failed"])
        task = await _seed_task(notify_session)

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        assert mock_client.create_post.await_count == 1
        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 1
        assert deliveries[0].profile_id == p_match.id

    async def test_one_failure_does_not_stop_others(self, notify_sf, notify_session):
        """If one profile's notification fails, others still succeed."""
        p1 = await _seed_profile(notify_session, name="Fail",
                                 team_name="bad", channel_name="gone", channel_id="bad-channel",
                                 events=["task_completed"])
        p2 = await _seed_profile(notify_session, name="OK",
                                 team_name="good", channel_name="ok", channel_id="good-channel",
                                 events=["task_completed"])
        task = await _seed_task(notify_session)

        mock_client = AsyncMock()

        async def _create_post(channel_id, message, props):
            if channel_id == "bad-channel":
                raise MattermostNotificationError("channel gone")
            return {"id": "post-ok"}

        mock_client.create_post.side_effect = _create_post

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 2
        statuses = {d.profile_id: d.status for d in deliveries}
        assert statuses[p1.id] == "failed"
        assert statuses[p2.id] == "success"

    async def test_channel_and_dm_profiles_together(self, notify_sf, notify_session):
        """Both channel and DM profiles can fire for the same event."""
        await _seed_profile(notify_session, name="Channel",
                                   target_type="channel", events=["task_completed"])
        await _seed_profile(notify_session, name="DM",
                                   target_type="initiator_dm", events=["task_completed"])
        task = await _seed_task(notify_session, initiator_username="alice")
        await _seed_user_mapping(notify_session, gitlab_username="alice",
                                 mattermost_user_id="mm-alice")

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}
        mock_client.create_direct_channel.return_value = {"id": "dm-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        assert mock_client.create_post.await_count == 2
        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 2
        assert all(d.status == "success" for d in deliveries)


# ---------------------------------------------------------------------------
# notify_task_event — event types and message content
# ---------------------------------------------------------------------------


class TestNotifyEventTypes:
    """Verify different event types produce correct messages and colors."""

    @pytest.mark.parametrize("event_type,expected_emoji,expected_color", [
        (MATTERMOST_EVENT_TASK_COMPLETED, "✅", "good"),
        (MATTERMOST_EVENT_TASK_FAILED, "❌", "danger"),
        (MATTERMOST_EVENT_TASK_RESCHEDULED, "🗓️", "#2080f0"),
        (MATTERMOST_EVENT_TASK_CANCELLED, "🛑", "#d03050"),
    ])
    async def test_event_type_emoji_and_color(self, notify_sf, notify_session,
                                               event_type, expected_emoji, expected_color):
        """Each event type uses the correct emoji and color."""
        status_map = {
            MATTERMOST_EVENT_TASK_COMPLETED: TaskStatus.COMPLETED,
            MATTERMOST_EVENT_TASK_FAILED: TaskStatus.FAILED,
            MATTERMOST_EVENT_TASK_RESCHEDULED: TaskStatus.PENDING,
            MATTERMOST_EVENT_TASK_CANCELLED: TaskStatus.CANCELLED,
        }
        await _seed_profile(notify_session, events=[event_type])
        task = await _seed_task(notify_session, status=status_map[event_type])

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, event_type)

        message = mock_client.create_post.await_args.args[1]
        assert expected_emoji in message

        props = mock_client.create_post.await_args.args[2]
        assert props["attachments"][0]["color"] == expected_color

    async def test_task_link_in_message(self, notify_sf, notify_session):
        """The message contains a link to the task dashboard page."""
        await _seed_profile(notify_session, events=["task_completed"])
        task = await _seed_task(notify_session, task_id=77)

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        message = mock_client.create_post.await_args.args[1]
        assert "https://dashboard.test.io/tasks/77" in message


# ---------------------------------------------------------------------------
# notify_task_event — context and schedule changes
# ---------------------------------------------------------------------------


class TestNotifyContext:
    """Verify context data (schedule changes, etc.) is reflected in notifications."""

    async def test_schedule_change_in_attachment_fields(self, notify_sf, notify_session):
        """Context with schedule change data produces schedule_change field."""
        from datetime import datetime
        await _seed_profile(notify_session, events=["task_rescheduled"],
                            fields=["task_id", "schedule_change", "scheduled_at"])
        task = await _seed_task(notify_session, status=TaskStatus.PENDING)

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        prev = datetime(2026, 4, 7, 10, 0, 0)
        new = datetime(2026, 4, 8, 14, 0, 0)

        with _patches(notify_sf, mock_client):
            await notify_task_event(
                task, MATTERMOST_EVENT_TASK_RESCHEDULED,
                context={"previous_scheduled_at": prev, "scheduled_at": new},
            )

        props = mock_client.create_post.await_args.args[2]
        fields = props["attachments"][0]["fields"]
        field_titles = [f["title"] for f in fields]
        assert "时间变更" in field_titles

        card = props["card"]
        assert "2026-04-07" in card
        assert "2026-04-08" in card

    async def test_error_message_in_failed_notification(self, notify_sf, notify_session):
        """Failed task error_message appears in attachment fields."""
        await _seed_profile(notify_session, events=["task_failed"],
                            fields=["task_id", "error"])
        task = await _seed_task(notify_session, status=TaskStatus.FAILED,
                                error_message="OOM: Container killed by cgroup")

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)

        props = mock_client.create_post.await_args.args[2]
        fields = props["attachments"][0]["fields"]
        error_field = [f for f in fields if f["title"] == "错误摘要"]
        assert len(error_field) == 1
        assert "OOM" in error_field[0]["value"]

    async def test_manual_task_shows_in_issue_field(self, notify_sf, notify_session):
        """All tasks have an issue now, so issue field shows issue_id."""
        await _seed_profile(notify_session, events=["task_completed"], fields=["task_id", "issue"])
        task = await _seed_task(notify_session)  # All tasks have an issue

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        props = mock_client.create_post.await_args.args[2]
        fields = props["attachments"][0]["fields"]
        issue_field = [f for f in fields if f["title"] == "Issue"]
        assert len(issue_field) == 1
        # Now shows issue_id instead of "手工任务"
        assert f"#{task.issue_id}" in issue_field[0]["value"]


# ---------------------------------------------------------------------------
# notify_task_event — delivery record target_summary
# ---------------------------------------------------------------------------


class TestNotifyDeliverySummary:
    """Verify target_summary values in delivery records."""

    async def test_channel_delivery_summary(self, notify_sf, notify_session):
        """Channel delivery summary is based on channel_id."""
        await _seed_profile(notify_session, team_name="myteam", channel_name="mychan",
                            events=["task_completed"])
        task = await _seed_task(notify_session)

        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "ch-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        deliveries = await _get_deliveries(notify_session, task.id)
        assert deliveries[0].target_summary == "channel:ch-seeded"

    async def test_dm_delivery_summary(self, notify_sf, notify_session):
        """DM delivery summary is 'dm:{username}'."""
        await _seed_profile(notify_session, target_type="initiator_dm",
                            events=["task_completed"])
        task = await _seed_task(notify_session, initiator_username="carol")
        await _seed_user_mapping(notify_session, gitlab_username="carol",
                                 mattermost_user_id="mm-carol")

        mock_client = AsyncMock()
        mock_client.create_direct_channel.return_value = {"id": "dm-001"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        deliveries = await _get_deliveries(notify_session, task.id)
        assert deliveries[0].target_summary == "dm:carol"

    async def test_dm_delivery_summary_no_initiator(self, notify_sf, notify_session):
        """DM delivery summary for missing initiator is 'dm:-'."""
        await _seed_profile(notify_session, target_type="initiator_dm",
                            events=["task_completed"])
        task = await _seed_task(notify_session, initiator_username=None)

        mock_client = AsyncMock()

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        deliveries = await _get_deliveries(notify_session, task.id)
        assert deliveries[0].target_summary == "dm:-"

    async def test_dm_succeeds_when_issue_not_preloaded(self, notify_sf, notify_session):
        """DM notification succeeds even when task.issue is not eagerly loaded.

        This simulates the worker code path where the task is loaded from the
        database with a plain select(Task) query and task.issue is never
        explicitly set before notify_task_event is called.
        """
        issue = await _seed_issue(notify_session)
        task = Task(
            project_id=10,
            issue_id=issue.id,
            user_prompt="test prompt",
            status=TaskStatus.COMPLETED,
            initiator_username="alice",
        )
        notify_session.add(task)
        await notify_session.commit()
        await notify_session.refresh(task)
        # At this point task.issue is unloaded (lazy relationship untouched)

        await _seed_profile(notify_session, target_type="initiator_dm",
                            events=["task_completed"])
        await _seed_user_mapping(notify_session, gitlab_username="alice",
                                 mattermost_user_id="mm-alice-1")

        mock_client = AsyncMock()
        mock_client.create_direct_channel.return_value = {"id": "dm-chan-x"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.create_direct_channel.assert_awaited_once_with("mm-alice-1")
        mock_client.create_post.assert_awaited_once()
        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 1
        assert deliveries[0].status == "success"

    async def test_dm_succeeds_when_task_has_no_issue(self, notify_sf, notify_session):
        """DM notification works when the task has no issue (issue_id is None)."""
        task = Task(
            project_id=10,
            issue_id=None,
            user_prompt="test prompt",
            status=TaskStatus.COMPLETED,
            initiator_username="bob",
        )
        notify_session.add(task)
        await notify_session.commit()
        await notify_session.refresh(task)

        await _seed_profile(notify_session, target_type="initiator_dm",
                            events=["task_completed"])
        await _seed_user_mapping(notify_session, gitlab_username="bob",
                                 mattermost_user_id="mm-bob-2")

        mock_client = AsyncMock()
        mock_client.create_direct_channel.return_value = {"id": "dm-chan-y"}

        with _patches(notify_sf, mock_client):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.create_direct_channel.assert_awaited_once_with("mm-bob-2")
        mock_client.create_post.assert_awaited_once()
        deliveries = await _get_deliveries(notify_session, task.id)
        assert len(deliveries) == 1
        assert deliveries[0].status == "success"
