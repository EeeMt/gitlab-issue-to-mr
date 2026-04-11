"""Unit tests for Mattermost API endpoints (backend/app/api/mattermost.py).

Covers: model validation, _normalize_updates helper, and all CRUD / test-connection
endpoints via direct async function calls with mocked dependencies.
"""

import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api.mattermost import (
    MattermostConnectionTestRequest,
    MattermostIntegrationUpdate,
    MattermostNotificationProfileInput,
    _normalize_updates,
    create_mattermost_notification_profile,
    delete_mattermost_notification_profile,
    get_mattermost_notification_config,
    test_mattermost_notification_integration as _endpoint_test_connection,
    update_mattermost_notification_integration,
    update_mattermost_notification_profile,
)
from app.core.mattermost_notifications import MattermostNotificationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_profile(
    pid=1,
    name="Test",
    enabled=True,
    target_type="channel",
    team_name="team",
    channel_name="chan",
):
    """Return a mock that quacks like a MattermostNotificationProfile row."""
    p = MagicMock()
    p.id = pid
    p.name = name
    p.enabled = enabled
    p.target_type = target_type
    p.team_name = team_name
    p.channel_name = channel_name
    p.mention_in_channel = False
    p.send_for_manual_tasks = False
    p.event_types_json = '["task_completed"]'
    p.field_keys_json = '["task_id"]'
    p.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    p.updated_at = datetime(2024, 1, 1, tzinfo=UTC)
    return p


def _mock_settings(server_url="https://mm.example.com", token="tok-123"):
    return SimpleNamespace(
        mattermost_server_url=server_url,
        mattermost_bot_token=token,
    )


def _mock_db(profiles=None):
    """Return an AsyncMock session pre-configured with profile query results."""
    db = AsyncMock()
    if profiles is not None:
        db.execute.return_value = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: profiles),
        )
    return db


# ===================================================================
# _normalize_updates
# ===================================================================

class TestNormalizeUpdates:
    """Tests for _normalize_updates helper."""

    def test_filters_none_values(self):
        """None values should be excluded from the result."""
        assert _normalize_updates({"a": None, "b": "ok"}) == {"b": "ok"}

    def test_filters_empty_string_values(self):
        """Whitespace-only strings should be excluded."""
        assert _normalize_updates({"a": "  ", "b": "ok"}) == {"b": "ok"}

    def test_keeps_valid_strings(self):
        """Non-empty strings pass through."""
        assert _normalize_updates({"url": "https://x"}) == {"url": "https://x"}

    def test_keeps_non_string_values(self):
        """Booleans and ints are preserved unchanged."""
        assert _normalize_updates({"flag": True, "count": 0}) == {"flag": True, "count": 0}

    def test_empty_dict(self):
        """Empty input yields empty output."""
        assert _normalize_updates({}) == {}


# ===================================================================
# MattermostNotificationProfileInput Pydantic validation
# ===================================================================

class TestProfileInputValidation:
    """Tests for MattermostNotificationProfileInput model_validator."""

    def test_empty_name_rejected(self):
        """A blank name must raise a validation error."""
        with pytest.raises(ValidationError, match="Profile name cannot be empty"):
            MattermostNotificationProfileInput(
                name="   ",
                target_type="channel",
                team_name="t",
                channel_name="c",
                event_types=["task_completed"],
                field_keys=["task_id"],
            )

    def test_invalid_target_type_rejected(self):
        """An unknown target_type must be rejected."""
        with pytest.raises(ValidationError, match="target_type must be one of"):
            MattermostNotificationProfileInput(
                name="p",
                target_type="email",
                event_types=["task_completed"],
                field_keys=["task_id"],
            )

    def test_no_event_types_rejected(self):
        """Empty event_types list must be rejected."""
        with pytest.raises(ValidationError, match="At least one event type must be selected"):
            MattermostNotificationProfileInput(
                name="p",
                target_type="channel",
                team_name="t",
                channel_name="c",
                event_types=[],
                field_keys=["task_id"],
            )

    def test_only_invalid_event_types_yields_empty_then_rejected(self):
        """If all supplied event types are invalid, the list normalises to empty → error."""
        with pytest.raises(ValidationError, match="At least one event type must be selected"):
            MattermostNotificationProfileInput(
                name="p",
                target_type="channel",
                team_name="t",
                channel_name="c",
                event_types=["bogus_event"],
                field_keys=["task_id"],
            )

    def test_no_field_keys_rejected(self):
        """Empty field_keys list must be rejected."""
        with pytest.raises(ValidationError, match="At least one field must be selected"):
            MattermostNotificationProfileInput(
                name="p",
                target_type="channel",
                team_name="t",
                channel_name="c",
                event_types=["task_completed"],
                field_keys=[],
            )

    def test_only_invalid_field_keys_yields_empty_then_rejected(self):
        """If all supplied field keys are invalid, the list normalises to empty → error."""
        with pytest.raises(ValidationError, match="At least one field must be selected"):
            MattermostNotificationProfileInput(
                name="p",
                target_type="channel",
                team_name="t",
                channel_name="c",
                event_types=["task_completed"],
                field_keys=["bogus_key"],
            )

    def test_channel_missing_team_name_rejected(self):
        """Channel target_type without team_name must be rejected."""
        with pytest.raises(ValidationError, match="Channel notifications require both"):
            MattermostNotificationProfileInput(
                name="p",
                target_type="channel",
                team_name=None,
                channel_name="c",
                event_types=["task_completed"],
                field_keys=["task_id"],
            )

    def test_channel_missing_channel_name_rejected(self):
        """Channel target_type without channel_name must be rejected."""
        with pytest.raises(ValidationError, match="Channel notifications require both"):
            MattermostNotificationProfileInput(
                name="p",
                target_type="channel",
                team_name="t",
                channel_name=None,
                event_types=["task_completed"],
                field_keys=["task_id"],
            )

    def test_non_channel_clears_team_channel_mention(self):
        """For initiator_dm, team_name/channel_name/mention must be cleared."""
        p = MattermostNotificationProfileInput(
            name="dm",
            target_type="initiator_dm",
            team_name="should_clear",
            channel_name="should_clear",
            mention_in_channel=True,
            event_types=["task_failed"],
            field_keys=["status"],
        )
        assert p.team_name is None
        assert p.channel_name is None
        assert p.mention_in_channel is False

    def test_valid_channel_profile_accepted(self):
        """A fully-valid channel profile should be accepted."""
        p = MattermostNotificationProfileInput(
            name="ok",
            target_type="channel",
            team_name="t",
            channel_name="c",
            event_types=["task_completed", "task_failed"],
            field_keys=["task_id", "status"],
        )
        assert p.name == "ok"
        assert p.target_type == "channel"
        assert p.event_types == ["task_completed", "task_failed"]

    def test_whitespace_is_stripped(self):
        """Leading/trailing spaces in name, target, team, channel must be stripped."""
        p = MattermostNotificationProfileInput(
            name="  myprof  ",
            target_type="  channel  ",
            team_name="  t  ",
            channel_name="  c  ",
            event_types=["task_completed"],
            field_keys=["task_id"],
        )
        assert p.name == "myprof"
        assert p.target_type == "channel"
        assert p.team_name == "t"
        assert p.channel_name == "c"


# ===================================================================
# GET /config/notifications
# ===================================================================

class TestGetNotificationConfig:
    """Tests for get_mattermost_notification_config endpoint."""

    @pytest.mark.asyncio
    async def test_returns_integration_and_profiles(self):
        """Endpoint returns integration settings and serialised profiles."""
        db = _mock_db(profiles=[_mock_profile()])

        with (
            patch("app.api.mattermost.load_runtime_config_from_db", new_callable=AsyncMock),
            patch("app.api.mattermost.get_effective_settings", return_value=_mock_settings()),
        ):
            result = await get_mattermost_notification_config(db=db, _current_user=MagicMock())

        assert result.integration.mattermost_server_url == "https://mm.example.com"
        assert result.integration.mattermost_bot_token_configured is True
        assert len(result.profiles) == 1
        assert result.profiles[0].name == "Test"

    @pytest.mark.asyncio
    async def test_empty_token_reports_not_configured(self):
        """When bot_token is empty the flag should be False."""
        db = _mock_db(profiles=[])

        with (
            patch("app.api.mattermost.load_runtime_config_from_db", new_callable=AsyncMock),
            patch("app.api.mattermost.get_effective_settings", return_value=_mock_settings(token="")),
        ):
            result = await get_mattermost_notification_config(db=db, _current_user=MagicMock())

        assert result.integration.mattermost_bot_token_configured is False


# ===================================================================
# PATCH /config/notifications/integration
# ===================================================================

class TestUpdateIntegration:
    """Tests for update_mattermost_notification_integration endpoint."""

    @pytest.mark.asyncio
    async def test_saves_new_server_url(self):
        """Updating server_url should call save_runtime_config_override."""
        db = _mock_db(profiles=[])
        req = MattermostIntegrationUpdate(mattermost_server_url="https://new.example.com")

        with (
            patch("app.api.mattermost.load_runtime_config_from_db", new_callable=AsyncMock),
            patch("app.api.mattermost.save_runtime_config_override", new_callable=AsyncMock) as mock_save,
            patch("app.api.mattermost.get_effective_settings", return_value=_mock_settings()),
        ):
            result = await update_mattermost_notification_integration(
                request=req, db=db, _current_user=MagicMock(),
            )

        mock_save.assert_awaited_once_with(db, "mattermost_server_url", "https://new.example.com")
        assert result.integration.mattermost_server_url == "https://mm.example.com"

    @pytest.mark.asyncio
    async def test_clears_bot_token(self):
        """Setting clear_mattermost_bot_token=True should call reset_runtime_config_override."""
        db = _mock_db(profiles=[])
        req = MattermostIntegrationUpdate(clear_mattermost_bot_token=True)

        with (
            patch("app.api.mattermost.load_runtime_config_from_db", new_callable=AsyncMock),
            patch("app.api.mattermost.save_runtime_config_override", new_callable=AsyncMock),
            patch("app.api.mattermost.reset_runtime_config_override", new_callable=AsyncMock) as mock_reset,
            patch("app.api.mattermost.get_effective_settings", return_value=_mock_settings()),
        ):
            await update_mattermost_notification_integration(
                request=req, db=db, _current_user=MagicMock(),
            )

        mock_reset.assert_awaited_once_with(db, "mattermost_bot_token")

    @pytest.mark.asyncio
    async def test_encryption_error_returns_500(self):
        """ConfigEncryptionError during save should surface as HTTP 500."""
        from app.core.config_crypto import ConfigEncryptionError
        from fastapi import HTTPException

        db = _mock_db(profiles=[])
        req = MattermostIntegrationUpdate(mattermost_server_url="https://x")

        with (
            patch("app.api.mattermost.load_runtime_config_from_db", new_callable=AsyncMock),
            patch(
                "app.api.mattermost.save_runtime_config_override",
                new_callable=AsyncMock,
                side_effect=ConfigEncryptionError("boom"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_mattermost_notification_integration(
                    request=req, db=db, _current_user=MagicMock(),
                )
            assert exc_info.value.status_code == 500


# ===================================================================
# POST /config/notifications/test
# ===================================================================

class TestTestConnection:
    """Tests for test_mattermost_notification_integration endpoint."""

    @pytest.mark.asyncio
    async def test_success_returns_server_and_username(self):
        """A successful test should return the server_url and username."""
        db = AsyncMock()
        req = MattermostConnectionTestRequest(
            integration=MattermostIntegrationUpdate(
                mattermost_server_url="https://mm.test.com",
                mattermost_bot_token="test-token",
            ),
        )

        with (
            patch("app.api.mattermost.load_runtime_config_from_db", new_callable=AsyncMock),
            patch("app.api.mattermost.get_effective_settings", return_value=_mock_settings()),
            patch(
                "app.core.mattermost_notifications.test_mattermost_connection",
                new_callable=AsyncMock,
                return_value={"server_url": "https://mm.test.com", "username": "bot"},
            ),
        ):
            result = await _endpoint_test_connection(
                request=req, db=db, _current_user=MagicMock(),
            )

        assert result.server_url == "https://mm.test.com"
        assert result.username == "bot"

    @pytest.mark.asyncio
    async def test_mattermost_error_returns_400(self):
        """MattermostNotificationError should map to HTTP 400."""
        from fastapi import HTTPException

        db = AsyncMock()
        req = MattermostConnectionTestRequest(
            integration=MattermostIntegrationUpdate(mattermost_server_url="https://mm.test.com"),
        )

        with (
            patch("app.api.mattermost.load_runtime_config_from_db", new_callable=AsyncMock),
            patch("app.api.mattermost.get_effective_settings", return_value=_mock_settings()),
            patch(
                "app.core.mattermost_notifications.test_mattermost_connection",
                new_callable=AsyncMock,
                side_effect=MattermostNotificationError("bad token"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _endpoint_test_connection(
                    request=req, db=db, _current_user=MagicMock(),
                )
            assert exc_info.value.status_code == 400
            assert "bad token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_httpx_error_returns_400(self):
        """httpx.HTTPError should map to HTTP 400."""
        from fastapi import HTTPException

        db = AsyncMock()
        req = MattermostConnectionTestRequest(
            integration=MattermostIntegrationUpdate(mattermost_server_url="https://mm.test.com"),
        )

        with (
            patch("app.api.mattermost.load_runtime_config_from_db", new_callable=AsyncMock),
            patch("app.api.mattermost.get_effective_settings", return_value=_mock_settings()),
            patch(
                "app.core.mattermost_notifications.test_mattermost_connection",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError("connection refused"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _endpoint_test_connection(
                    request=req, db=db, _current_user=MagicMock(),
                )
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_uses_stored_token_when_no_override(self):
        """When no bot_token override is supplied, the stored one is used."""
        db = AsyncMock()
        req = MattermostConnectionTestRequest(
            integration=MattermostIntegrationUpdate(mattermost_server_url="https://mm.test.com"),
        )

        with (
            patch("app.api.mattermost.load_runtime_config_from_db", new_callable=AsyncMock),
            patch("app.api.mattermost.get_effective_settings", return_value=_mock_settings(token="stored-token")),
            patch(
                "app.core.mattermost_notifications.test_mattermost_connection",
                new_callable=AsyncMock,
                return_value={"server_url": "https://mm.test.com", "username": "bot"},
            ) as mock_test,
        ):
            await _endpoint_test_connection(
                request=req, db=db, _current_user=MagicMock(),
            )

        # The stored token should have been forwarded
        mock_test.assert_awaited_once()
        call_kwargs = mock_test.await_args.kwargs
        assert call_kwargs["bot_token"] == "stored-token"

    @pytest.mark.asyncio
    async def test_clear_flag_passes_empty_token(self):
        """clear_mattermost_bot_token=True should pass an empty token to the test helper."""
        db = AsyncMock()
        req = MattermostConnectionTestRequest(
            integration=MattermostIntegrationUpdate(clear_mattermost_bot_token=True),
        )

        with (
            patch("app.api.mattermost.load_runtime_config_from_db", new_callable=AsyncMock),
            patch("app.api.mattermost.get_effective_settings", return_value=_mock_settings()),
            patch(
                "app.core.mattermost_notifications.test_mattermost_connection",
                new_callable=AsyncMock,
                side_effect=MattermostNotificationError("empty token"),
            ),
        ):
            # We expect it to fail because the token is empty, but the point is
            # it *tried* with an empty token.
            from fastapi import HTTPException

            with pytest.raises(HTTPException):
                await _endpoint_test_connection(
                    request=req, db=db, _current_user=MagicMock(),
                )


# ===================================================================
# POST /config/notifications/profiles  (create)
# ===================================================================

class TestCreateProfile:
    """Tests for create_mattermost_notification_profile endpoint."""

    @pytest.mark.asyncio
    async def test_creates_and_returns_profile(self):
        """A valid payload should persist and return the serialised profile."""
        db = AsyncMock()
        # db.add is synchronous in SQLAlchemy – use a plain MagicMock to avoid
        # the "coroutine never awaited" warning from AsyncMock.
        db.add = MagicMock()

        async def _fake_refresh(obj):
            obj.id = 42
            obj.created_at = datetime(2024, 6, 1, tzinfo=UTC)
            obj.updated_at = datetime(2024, 6, 1, tzinfo=UTC)

        db.refresh = AsyncMock(side_effect=_fake_refresh)

        payload = MattermostNotificationProfileInput(
            name="new-channel",
            target_type="channel",
            team_name="eng",
            channel_name="alerts",
            event_types=["task_completed"],
            field_keys=["task_id", "status"],
        )

        result = await create_mattermost_notification_profile(
            payload=payload, db=db, _current_user=MagicMock(),
        )

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once()
        assert result.id == 42
        assert result.name == "new-channel"
        assert result.target_type == "channel"
        assert result.event_types == ["task_completed"]


# ===================================================================
# PATCH /config/notifications/profiles/{profile_id}  (update)
# ===================================================================

class TestUpdateProfile:
    """Tests for update_mattermost_notification_profile endpoint."""

    @pytest.mark.asyncio
    async def test_updates_existing_profile(self):
        """Updating an existing profile should modify and return it."""
        profile = _mock_profile(pid=5)
        db = AsyncMock()
        db.get = AsyncMock(return_value=profile)

        async def _refresh(obj):
            obj.created_at = datetime(2024, 1, 1, tzinfo=UTC)
            obj.updated_at = datetime(2024, 7, 1, tzinfo=UTC)

        db.refresh = AsyncMock(side_effect=_refresh)

        payload = MattermostNotificationProfileInput(
            name="renamed",
            target_type="channel",
            team_name="team2",
            channel_name="chan2",
            event_types=["task_failed"],
            field_keys=["status"],
        )

        result = await update_mattermost_notification_profile(
            profile_id=5, payload=payload, db=db, _current_user=MagicMock(),
        )

        db.commit.assert_awaited_once()
        assert profile.name == "renamed"
        assert profile.team_name == "team2"
        assert result.name == "renamed"

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(self):
        """Updating a non-existent profile should raise HTTP 404."""
        from fastapi import HTTPException

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        payload = MattermostNotificationProfileInput(
            name="x",
            target_type="channel",
            team_name="t",
            channel_name="c",
            event_types=["task_completed"],
            field_keys=["task_id"],
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_mattermost_notification_profile(
                profile_id=999, payload=payload, db=db, _current_user=MagicMock(),
            )

        assert exc_info.value.status_code == 404
        assert "999" in exc_info.value.detail


# ===================================================================
# DELETE /config/notifications/profiles/{profile_id}
# ===================================================================

class TestDeleteProfile:
    """Tests for delete_mattermost_notification_profile endpoint."""

    @pytest.mark.asyncio
    async def test_deletes_existing_profile(self):
        """Deleting an existing profile should commit and return success."""
        profile = _mock_profile(pid=3)
        db = AsyncMock()
        db.get = AsyncMock(return_value=profile)

        result = await delete_mattermost_notification_profile(
            profile_id=3, db=db, _current_user=MagicMock(),
        )

        db.delete.assert_awaited_once_with(profile)
        db.commit.assert_awaited_once()
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(self):
        """Deleting a non-existent profile should raise HTTP 404."""
        from fastapi import HTTPException

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await delete_mattermost_notification_profile(
                profile_id=777, db=db, _current_user=MagicMock(),
            )

        assert exc_info.value.status_code == 404
        assert "777" in exc_info.value.detail
