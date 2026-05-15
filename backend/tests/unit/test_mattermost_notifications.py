#!/usr/bin/env python3
"""Unit tests for Mattermost task notifications."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.mattermost_notifications import (
    MATTERMOST_EVENT_TASK_COMPLETED,
    MATTERMOST_EVENT_TASK_FAILED,
    MATTERMOST_TARGET_TYPE_CHANNEL,
    MATTERMOST_TARGET_TYPE_INITIATOR_DM,
    notify_task_event,
)
from app.models import Issue, MattermostNotificationProfile, Task, TaskStatus


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class MattermostNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_task_event_posts_to_configured_channel(self) -> None:
        task = Task(
            id=7,
            project_id=12,
            user_prompt="ship it",
            status=TaskStatus.COMPLETED,
            initiator_username="alice",
        )
        task.issue_id = 34
        task.__dict__["issue"] = SimpleNamespace(
            branch_name="feature/demo",
            target_branch="main",
            merge_request_iid=None,
            merge_request_url=None,
        )
        profile = MattermostNotificationProfile(
            id=1,
            name="Channel",
            enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_CHANNEL,
            channel_id="channel-1",
            mention_in_channel=True,
            event_types_json='["task_completed"]',
            field_keys_json='["task_id","status"]',
        )
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [profile])
        )
        mock_client = AsyncMock()
        with patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            return_value=_SessionContext(mock_session),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mattermost.example.com",
                mattermost_bot_token="mm-token",
                dashboard_url="https://bot.example.com",
            ),
        ):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.get_channel_by_name.assert_not_called()
        create_post_args = mock_client.create_post.await_args.args
        self.assertEqual(create_post_args[0], "channel-1")
        self.assertIn("@alice", create_post_args[1])
        self.assertEqual(mock_session.commit.await_count, 1)

    async def test_notify_task_event_fails_when_channel_id_missing(self) -> None:
        task = Task(
            id=8,
            project_id=12,
            user_prompt="ship it",
            status=TaskStatus.COMPLETED,
            initiator_username="alice",
        )
        task.issue_id = 35
        task.__dict__["issue"] = SimpleNamespace(
            branch_name="feature/fallback",
            target_branch="main",
            merge_request_iid=None,
            merge_request_url=None,
        )
        profile = MattermostNotificationProfile(
            id=2,
            name="Channel fallback",
            enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_CHANNEL,
            channel_id=None,
            mention_in_channel=False,
            event_types_json='["task_completed"]',
            field_keys_json='["task_id"]',
        )
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [profile])
        )
        mock_client = AsyncMock()

        with patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            return_value=_SessionContext(mock_session),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mattermost.example.com",
                mattermost_bot_token="mm-token",
                dashboard_url="https://bot.example.com",
            ),
        ):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.get_channel_by_name.assert_not_called()
        mock_client.create_post.assert_not_called()
        add_calls = mock_session.add.call_args_list
        self.assertTrue(any(
            getattr(c.args[0], "status", None) == "failed"
            for c in add_calls
        ))

    async def test_notify_task_event_skips_dm_when_initiator_missing(self) -> None:
        task = Task(
            id=9,
            project_id=12,
            user_prompt="ship it",
            status=TaskStatus.FAILED,
            initiator_username=None,
        )
        task.issue_id = 34
        task.__dict__["issue"] = SimpleNamespace(
            branch_name="feature/demo",
            target_branch="main",
            merge_request_iid=None,
            merge_request_url=None,
        )
        profile = MattermostNotificationProfile(
            id=2,
            name="DM",
            enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_INITIATOR_DM,
            mention_in_channel=False,
            event_types_json='["task_failed"]',
            field_keys_json='["task_id","status"]',
        )
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [profile])
        )
        mock_client = AsyncMock()

        with patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            return_value=_SessionContext(mock_session),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mattermost.example.com",
                mattermost_bot_token="mm-token",
                dashboard_url="https://bot.example.com",
            ),
        ):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)

        mock_client.create_direct_channel.assert_not_called()
        self.assertTrue(mock_session.add.called)
        self.assertEqual(mock_session.commit.await_count, 1)


class TestNotifyTaskEventAdditional(unittest.IsolatedAsyncioTestCase):
    """Additional notify_task_event tests for uncovered branches."""

    async def test_invalid_event_type_raises_value_error(self) -> None:
        """Unsupported event type must raise ValueError."""
        task = Task(
            id=1, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        with self.assertRaises(ValueError, msg="Unsupported Mattermost event type"):
            await notify_task_event(task, "not_a_valid_event")

    async def test_returns_early_when_server_url_empty(self) -> None:
        """No-op when server_url is blank (no profiles queried)."""
        task = Task(
            id=2, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        with patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="",
                mattermost_bot_token="token",
                dashboard_url="https://dash",
            ),
        ):
            # Should return without touching the database at all
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

    async def test_returns_early_when_bot_token_empty(self) -> None:
        """No-op when bot_token is blank."""
        task = Task(
            id=3, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        with patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mm",
                mattermost_bot_token="  ",
                dashboard_url="https://dash",
            ),
        ):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

    async def test_returns_early_when_no_profiles(self) -> None:
        """No-op when there are zero enabled profiles."""
        task = Task(
            id=4, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [])
            )
        )
        mock_session.commit = AsyncMock()
        mock_client = AsyncMock()

        with patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            return_value=_SessionContext(mock_session),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mm",
                mattermost_bot_token="tok",
                dashboard_url="https://dash",
            ),
        ):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.create_post.assert_not_called()

    async def test_skips_profile_when_event_not_in_list(self) -> None:
        """Profile should be skipped if event_type is not in the profile's list."""
        task = Task(
            id=5, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        profile = MattermostNotificationProfile(
            id=1, name="C", enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_CHANNEL,
            channel_id="channel-1",
            mention_in_channel=False,
            event_types_json='["task_failed"]',
            field_keys_json='["task_id"]',
        )
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [profile])
            )
        )
        mock_session.commit = AsyncMock()
        mock_client = AsyncMock()

        with patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            return_value=_SessionContext(mock_session),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mm",
                mattermost_bot_token="tok",
                dashboard_url="https://dash",
            ),
        ):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        mock_client.create_post.assert_not_called()

    async def test_dm_notification_success(self) -> None:
        """Successful DM notification should create direct channel and post."""
        task = Task(
            id=10, project_id=1, user_prompt="x",
            status=TaskStatus.FAILED, initiator_username="bob",
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        profile = MattermostNotificationProfile(
            id=2, name="DM", enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_INITIATOR_DM,
            mention_in_channel=False,
            event_types_json='["task_failed"]',
            field_keys_json='["task_id","status"]',
        )
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [profile])
            )
        )
        mock_session.commit = AsyncMock()
        mock_client = AsyncMock()
        mock_client.create_direct_channel.return_value = {"id": "dm-chan-1"}

        with patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            return_value=_SessionContext(mock_session),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mm",
                mattermost_bot_token="tok",
                dashboard_url="https://dash",
            ),
        ), patch(
            "app.core.mattermost_notifications._resolve_mattermost_user_id",
            new_callable=AsyncMock,
            return_value="mm-user-42",
        ):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)

        mock_client.create_direct_channel.assert_awaited_once_with("mm-user-42")
        mock_client.create_post.assert_awaited_once()
        post_args = mock_client.create_post.await_args.args
        self.assertEqual(post_args[0], "dm-chan-1")

    async def test_channel_missing_channel_id_raises_and_logs_failed(self) -> None:
        """Channel profile with missing channel_id should log as failed."""
        task = Task(
            id=11, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED, initiator_username="alice",
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        profile = MattermostNotificationProfile(
            id=3, name="BadChan", enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_CHANNEL,
            channel_id=None,
            mention_in_channel=False,
            event_types_json='["task_completed"]',
            field_keys_json='["task_id"]',
        )
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [profile])
            )
        )
        mock_session.commit = AsyncMock()
        mock_client = AsyncMock()

        with patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            return_value=_SessionContext(mock_session),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mm",
                mattermost_bot_token="tok",
                dashboard_url="https://dash",
            ),
        ):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        # The exception handler should have logged a "failed" delivery
        add_calls = mock_session.add.call_args_list
        self.assertTrue(any(
            getattr(c.args[0], "status", None) == "failed"
            for c in add_calls
        ))

    async def test_api_exception_logs_failed_delivery(self) -> None:
        """When the Mattermost API raises, a 'failed' delivery row should be logged."""
        task = Task(
            id=12, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED, initiator_username="alice",
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        profile = MattermostNotificationProfile(
            id=4, name="C", enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_CHANNEL,
            channel_id="channel-1",
            mention_in_channel=False,
            event_types_json='["task_completed"]',
            field_keys_json='["task_id"]',
        )
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [profile])
            )
        )
        mock_session.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.create_post.side_effect = RuntimeError("connection lost")

        with patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            return_value=_SessionContext(mock_session),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mm",
                mattermost_bot_token="tok",
                dashboard_url="https://dash",
            ),
        ):
            # Should NOT raise; the exception is caught and logged
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        add_calls = mock_session.add.call_args_list
        failed = [c for c in add_calls if getattr(c.args[0], "status", None) == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("connection lost", failed[0].args[0].error_message)

    async def test_expired_task_reloaded_and_notification_sent(self) -> None:
        """When a task is expired (after intermediate db.commit()), it is reloaded
        from DB and the notification is sent successfully.

        This is a regression test for the bug where completion notifications were
        silently dropped because db.commit() in monitor_container_run expired the
        task's SQLAlchemy state, causing attribute access to raise MissingGreenlet.
        """
        # Build the fresh task that will be returned by the reload query
        reloaded_task = Task(
            id=13, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED, initiator_username="alice",
        )
        reloaded_task.issue_id = None  # no issue → simpler path
        reloaded_task.__dict__.pop("issue", None)

        profile = MattermostNotificationProfile(
            id=5, name="C", enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_CHANNEL,
            channel_id="channel-1",
            mention_in_channel=False,
            event_types_json='["task_completed"]',
            field_keys_json='["task_id","status"]',
        )

        # The reload session returns the reloaded task; the profile session returns profiles
        reload_session = MagicMock()
        reload_session.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalar_one_or_none=lambda: reloaded_task
            )
        )
        reload_session.expunge = MagicMock()

        profile_session = MagicMock()
        profile_session.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [profile])
            )
        )
        profile_session.commit = AsyncMock()

        session_call_count = 0

        class _MultiSessionContext:
            """Returns reload_session on first call, profile_session on second."""
            def __init__(self_inner):
                pass
            async def __aenter__(self_inner):
                nonlocal session_call_count
                session_call_count += 1
                return reload_session if session_call_count == 1 else profile_session
            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        mock_client = AsyncMock()

        # Simulate the expired state: inspect(task).expired is True, identity = (13,)
        expired_state = MagicMock()
        expired_state.expired = True
        expired_state.identity = (13,)

        original_task = Task(id=13, project_id=1, user_prompt="x", status=TaskStatus.COMPLETED)

        with patch(
            "app.core.mattermost_notifications.inspect",
            side_effect=lambda obj: expired_state if obj is original_task else __import__("sqlalchemy").inspect(obj),
        ), patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            return_value=_MultiSessionContext(),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mm",
                mattermost_bot_token="tok",
                dashboard_url="https://dash",
            ),
        ):
            await notify_task_event(original_task, MATTERMOST_EVENT_TASK_COMPLETED)

        # Reload session was used (expunge called for reloaded task)
        reload_session.expunge.assert_called()
        # Notification was posted
        mock_client.create_post.assert_awaited_once()
        post_args = mock_client.create_post.await_args.args
        self.assertEqual(post_args[0], "channel-1")

    async def test_unloaded_issue_does_not_detach_caller_task(self) -> None:
        """Loading an unloaded issue for rendering must not mutate the caller's session.

        Successful task notifications run before monitor_container_run commits the
        final task status and stats.  Detaching the caller's Task there can make
        the later commit miss those changes, while failed/retry paths already
        have the terminal state persisted before notifying.
        """
        task = Task(
            id=14,
            project_id=1,
            issue_id=44,
            user_prompt="x",
            status=TaskStatus.COMPLETED,
            initiator_username="alice",
        )

        issue = Issue(
            id=44,
            project_id=1,
            title="Notify",
            description="Notify",
            branch_name="feature/notify",
            target_branch="main",
            merge_request_iid=7,
            merge_request_url="https://gitlab.example.com/project/-/merge_requests/7",
        )
        profile = MattermostNotificationProfile(
            id=6,
            name="C",
            enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_CHANNEL,
            channel_id="channel-1",
            mention_in_channel=False,
            event_types_json='["task_completed"]',
            field_keys_json='["task_id","status","merge_request"]',
        )

        caller_session = MagicMock()
        task_state = MagicMock()
        task_state.expired = False
        task_state.unloaded = {"issue"}
        task_state.session = caller_session

        issue_session = MagicMock()
        issue_session.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: issue)
        )
        issue_session.expunge = MagicMock()

        profile_session = MagicMock()
        profile_session.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [profile])
            )
        )
        profile_session.commit = AsyncMock()

        session_call_count = 0

        class _MultiSessionContext:
            async def __aenter__(self_inner):
                nonlocal session_call_count
                session_call_count += 1
                return issue_session if session_call_count == 1 else profile_session

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        mock_client = AsyncMock()

        with patch(
            "app.core.mattermost_notifications.inspect",
            return_value=task_state,
        ), patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            return_value=_MultiSessionContext(),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mm",
                mattermost_bot_token="tok",
                dashboard_url="https://dash",
            ),
        ):
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)

        caller_session.expunge.assert_not_called()
        issue_session.expunge.assert_called_once_with(issue)
        mock_client.create_post.assert_awaited_once()

    async def test_custom_session_factory_is_used_for_database_queries(self) -> None:
        """Worker threads must be able to keep notification queries on their loop."""
        task = Task(
            id=15,
            project_id=1,
            issue_id=45,
            user_prompt="x",
            status=TaskStatus.COMPLETED,
            initiator_username="alice",
        )
        task.__dict__.pop("issue", None)

        issue = Issue(
            id=45,
            project_id=1,
            title="Notify",
            description="Notify",
            branch_name="feature/thread-local-session",
            target_branch="main",
            merge_request_iid=8,
            merge_request_url="https://gitlab.example.com/project/-/merge_requests/8",
        )
        profile = MattermostNotificationProfile(
            id=7,
            name="C",
            enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_CHANNEL,
            channel_id="channel-1",
            mention_in_channel=False,
            event_types_json='["task_completed"]',
            field_keys_json='["task_id","status"]',
        )

        issue_session = MagicMock()
        issue_session.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: issue)
        )
        issue_session.expunge = MagicMock()

        profile_session = MagicMock()
        profile_session.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [profile])
            )
        )
        profile_session.commit = AsyncMock()

        session_factory = MagicMock(
            side_effect=[
                _SessionContext(issue_session),
                _SessionContext(profile_session),
            ]
        )
        mock_client = AsyncMock()
        task_state = MagicMock()
        task_state.expired = False
        task_state.unloaded = {"issue"}

        def default_session_factory():
            raise AssertionError("default AsyncSessionLocal should not be used")

        with patch(
            "app.core.mattermost_notifications.inspect",
            return_value=task_state,
        ), patch(
            "app.core.mattermost_notifications.AsyncSessionLocal",
            side_effect=default_session_factory,
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ), patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mm",
                mattermost_bot_token="tok",
                dashboard_url="https://dash",
            ),
        ):
            await notify_task_event(
                task,
                MATTERMOST_EVENT_TASK_COMPLETED,
                session_factory=session_factory,
            )

        self.assertEqual(session_factory.call_count, 2)
        issue_session.expunge.assert_called_once_with(issue)
        mock_client.create_post.assert_awaited_once()


# =======================================================================
# Pure-function tests (no async, no DB)
# =======================================================================

import pytest
from datetime import datetime, timezone

from app.core.mattermost_notifications import (
    MattermostClient,
    MattermostNotificationError,
    deserialize_string_list,
    normalize_string_list,
    serialize_profile,
    serialize_string_list,
    test_mattermost_connection as _fn_test_mattermost_connection,
    _build_attachment_fields,
    _build_card_markdown,
    _event_color,
    _event_emoji,
    _event_label,
    _format_datetime,
    _resolve_mattermost_user_id,
    MATTERMOST_EVENT_TASK_FAILED,
    MATTERMOST_EVENT_TASK_RESCHEDULED,
    MATTERMOST_EVENT_TASK_EXECUTE_NOW,
    MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
    MATTERMOST_EVENT_TASK_CANCELLED,
    MATTERMOST_FIELD_TASK_ID,
    MATTERMOST_FIELD_PROJECT,
    MATTERMOST_FIELD_ISSUE,
    MATTERMOST_FIELD_STATUS,
    MATTERMOST_FIELD_BRANCH,
    MATTERMOST_FIELD_INITIATOR,
    MATTERMOST_FIELD_MERGE_REQUEST,
    MATTERMOST_FIELD_TARGET_BRANCH,
    MATTERMOST_FIELD_SCHEDULED_AT,
    MATTERMOST_FIELD_SCHEDULE_CHANGE,
    MATTERMOST_FIELD_ERROR,
    MATTERMOST_FIELD_TASK_LINK,
)


# ---- deserialize_string_list ----

class TestDeserializeStringList:
    def test_empty_string_returns_empty_list(self):
        """Empty raw value → empty list (line 87)."""
        assert deserialize_string_list("") == []

    def test_none_returns_empty_list(self):
        """None raw value → empty list (line 87, falsy check)."""
        assert deserialize_string_list(None) == []

    def test_invalid_json_returns_empty_list(self):
        """Malformed JSON → empty list (lines 91-92)."""
        assert deserialize_string_list("{not json}") == []

    def test_non_list_json_returns_empty_list(self):
        """JSON that is not a list → empty list (line 95)."""
        assert deserialize_string_list('{"a": 1}') == []

    def test_valid_list(self):
        """Well-formed JSON list of strings → parsed list."""
        assert deserialize_string_list('["task_completed", "task_failed"]') == [
            "task_completed",
            "task_failed",
        ]

    def test_strips_whitespace_and_skips_empty(self):
        """Strings with only whitespace are excluded, others are stripped."""
        assert deserialize_string_list('["  a  ", "  ", "b"]') == ["a", "b"]

    def test_non_string_items_ignored(self):
        """Non-string items in the list are skipped."""
        assert deserialize_string_list('[1, "ok", null, true]') == ["ok"]


# ---- serialize_string_list ----

class TestSerializeStringList:
    def test_round_trip(self):
        """serialize → deserialize should be identity."""
        original = ["task_completed", "task_failed"]
        assert deserialize_string_list(serialize_string_list(original)) == original

    def test_serializes_to_json_string(self):
        """Output must be a valid JSON string (line 108)."""
        result = serialize_string_list(["a", "b"])
        assert result == '["a", "b"]'


# ---- normalize_string_list ----

class TestNormalizeStringList:
    def test_filters_unknown_values(self):
        """Values not in the allowed set are excluded."""
        assert normalize_string_list(["ok", "nope"], {"ok"}) == ["ok"]

    def test_deduplicates(self):
        """Duplicate values should appear only once."""
        assert normalize_string_list(["a", "a", "b"], {"a", "b"}) == ["a", "b"]

    def test_strips_whitespace(self):
        """Leading/trailing whitespace is stripped before matching."""
        assert normalize_string_list(["  a  "], {"a"}) == ["a"]

    def test_empty_strings_skipped(self):
        """Blank strings are silently skipped."""
        assert normalize_string_list(["", "  ", "a"], {"a"}) == ["a"]


# ---- serialize_profile ----

class TestSerializeProfile:
    def test_converts_profile_to_dict(self):
        """serialize_profile must return a dict with deserialized JSON fields (line 128)."""
        p = MagicMock()
        p.id = 1
        p.name = "Test"
        p.enabled = True
        p.target_type = "channel"
        p.channel_id = "chan-1"
        p.mention_in_channel = False
        p.event_types_json = '["task_completed"]'
        p.field_keys_json = '["task_id", "status"]'
        p.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        p.updated_at = datetime(2024, 1, 2, tzinfo=timezone.utc)

        result = serialize_profile(p)

        assert result["id"] == 1
        assert result["event_types"] == ["task_completed"]
        assert result["field_keys"] == ["task_id", "status"]
        assert result["channel_id"] == "chan-1"
        assert "send_for_manual_tasks" not in result


# ---- _format_datetime ----

class TestFormatDatetime:
    def test_none_returns_dash(self):
        """None → '-'."""
        assert _format_datetime(None) == "-"

    def test_datetime_returns_iso(self):
        """A datetime is formatted as ISO with seconds precision (line 147)."""
        dt = datetime(2024, 6, 15, 10, 30, 45, tzinfo=timezone.utc)
        assert _format_datetime(dt) == "2024-06-15T10:30:45+00:00"


# ---- _event_label, _event_emoji, _event_color ----

class TestEventHelpers:
    def test_known_event_label(self):
        assert _event_label(MATTERMOST_EVENT_TASK_COMPLETED) == "任务完成"
        assert _event_label(MATTERMOST_EVENT_TASK_FAILED) == "任务失败"
        assert _event_label(MATTERMOST_EVENT_TASK_RESCHEDULED) == "任务改期"
        assert _event_label(MATTERMOST_EVENT_TASK_EXECUTE_NOW) == "任务改为立即执行"
        assert _event_label(MATTERMOST_EVENT_TASK_RETRY_SCHEDULED) == "任务重试已安排"
        assert _event_label(MATTERMOST_EVENT_TASK_CANCELLED) == "任务已取消"

    def test_unknown_event_label_falls_back(self):
        assert _event_label("unknown") == "任务通知"

    def test_known_event_emoji(self):
        assert _event_emoji(MATTERMOST_EVENT_TASK_COMPLETED) == "✅"
        assert _event_emoji(MATTERMOST_EVENT_TASK_FAILED) == "❌"

    def test_unknown_event_emoji_falls_back(self):
        assert _event_emoji("unknown") == "ℹ️"

    def test_known_event_color(self):
        assert _event_color(MATTERMOST_EVENT_TASK_COMPLETED) == "good"
        assert _event_color(MATTERMOST_EVENT_TASK_FAILED) == "danger"

    def test_unknown_event_color_falls_back(self):
        assert _event_color("unknown") == "#2080f0"


# ---- MattermostClient ----

def _make_client():
    """Create a MattermostClient with a mocked internal httpx client."""
    with patch("app.core.mattermost_notifications.get_ssl_verify", return_value=True):
        client = MattermostClient("https://mm.example.com/", "  token123  ")
    client._client = AsyncMock()
    return client


class TestMattermostClient:
    def test_init_strips_url_and_token(self):
        """Constructor should strip trailing slash from URL and whitespace from token."""
        with patch("app.core.mattermost_notifications.get_ssl_verify", return_value=True):
            c = MattermostClient("https://mm.example.com/", "  mytoken  ")
        assert c.server_url == "https://mm.example.com"
        assert c.bot_token == "mytoken"

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self):
        """close() should delegate to the internal client's aclose() (line 201)."""
        c = _make_client()
        await c.close()
        c._client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_request_success(self):
        """_request should return parsed JSON on 2xx (lines 204-208)."""
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "abc"}
        c._client.request = AsyncMock(return_value=mock_resp)

        result = await c._request("GET", "/users/me")
        assert result == {"id": "abc"}

    @pytest.mark.asyncio
    async def test_request_error_raises(self):
        """_request should raise MattermostNotificationError on 4xx+ (lines 206-207)."""
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_resp.reason_phrase = "Forbidden"
        c._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(MattermostNotificationError, match="403"):
            await c._request("GET", "/users/me")

    @pytest.mark.asyncio
    async def test_request_error_uses_reason_when_text_empty(self):
        """When response text is blank, reason_phrase is used as detail."""
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "   "
        mock_resp.reason_phrase = "Internal Server Error"
        c._client.request = AsyncMock(return_value=mock_resp)

        with pytest.raises(MattermostNotificationError, match="Internal Server Error"):
            await c._request("GET", "/test")

    @pytest.mark.asyncio
    async def test_get_me_caches(self):
        """get_me() should cache the result after the first call (lines 211-213)."""
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "u1", "username": "bot"}
        c._client.request = AsyncMock(return_value=mock_resp)

        result1 = await c.get_me()
        result2 = await c.get_me()
        assert result1 == result2
        # Only one HTTP request should have been made
        assert c._client.request.await_count == 1

    @pytest.mark.asyncio
    async def test_get_user_by_username(self):
        """get_user_by_username should call the correct path (line 216)."""
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "u2", "username": "alice"}
        c._client.request = AsyncMock(return_value=mock_resp)

        result = await c.get_user_by_username("alice")
        assert result["username"] == "alice"
        c._client.request.assert_awaited_once_with("GET", "/users/username/alice", json=None)

    @pytest.mark.asyncio
    async def test_get_channel_by_name(self):
        """get_channel_by_name should first resolve team then channel (lines 219-220)."""
        c = _make_client()
        responses = [
            # team lookup
            MagicMock(status_code=200, json=MagicMock(return_value={"id": "team-1"})),
            # channel lookup
            MagicMock(status_code=200, json=MagicMock(return_value={"id": "chan-1", "name": "general"})),
        ]
        c._client.request = AsyncMock(side_effect=responses)

        result = await c.get_channel_by_name("engineering", "general")
        assert result["id"] == "chan-1"
        assert c._client.request.await_count == 2

    @pytest.mark.asyncio
    async def test_create_direct_channel(self):
        """create_direct_channel should POST [me_id, other_id] (lines 223-224)."""
        c = _make_client()
        # First call: get_me
        me_resp = MagicMock(status_code=200, json=MagicMock(return_value={"id": "me-1", "username": "bot"}))
        # Second call: POST /channels/direct
        dc_resp = MagicMock(status_code=200, json=MagicMock(return_value={"id": "dm-chan-1"}))
        c._client.request = AsyncMock(side_effect=[me_resp, dc_resp])

        result = await c.create_direct_channel("other-user-1")
        assert result["id"] == "dm-chan-1"
        # Verify the POST body included both user IDs
        post_call = c._client.request.await_args_list[1]
        assert post_call.args == ("POST", "/channels/direct")
        assert post_call.kwargs["json"] == ["me-1", "other-user-1"]

    @pytest.mark.asyncio
    async def test_create_post(self):
        """create_post should POST with channel_id, message, and props (line 227)."""
        c = _make_client()
        mock_resp = MagicMock(status_code=200, json=MagicMock(return_value={"id": "post-1"}))
        c._client.request = AsyncMock(return_value=mock_resp)

        result = await c.create_post("chan-1", "hello", {"key": "val"})
        assert result["id"] == "post-1"
        post_call = c._client.request.await_args
        assert post_call.kwargs["json"]["channel_id"] == "chan-1"
        assert post_call.kwargs["json"]["message"] == "hello"


# ---- test_mattermost_connection ----

class TestTestMattermostConnection:
    @pytest.mark.asyncio
    async def test_success_returns_url_and_username(self):
        """Successful connection returns server_url and username (lines 244-257)."""
        mock_client = AsyncMock()
        mock_client.get_me.return_value = {"id": "u1", "username": "bot-user"}

        with patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://mm.example.com",
                mattermost_bot_token="tok",
            ),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ):
            result = await _fn_test_mattermost_connection(
                server_url="https://mm.test.com",
                bot_token="test-token",
            )

        assert result == {"server_url": "https://mm.test.com", "username": "bot-user"}
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_config_raises(self):
        """Blank server_url or bot_token raises MattermostNotificationError."""
        with patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="",
                mattermost_bot_token="",
            ),
        ):
            with pytest.raises(MattermostNotificationError, match="must both be configured"):
                await _fn_test_mattermost_connection()

    @pytest.mark.asyncio
    async def test_uses_settings_when_no_overrides(self):
        """When no explicit args, values from settings are used."""
        mock_client = AsyncMock()
        mock_client.get_me.return_value = {"id": "u1", "username": "default-bot"}

        with patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(
                mattermost_server_url="https://default.mm.com",
                mattermost_bot_token="default-tok",
            ),
        ), patch(
            "app.core.mattermost_notifications.MattermostClient",
            return_value=mock_client,
        ) as mock_cls:
            result = await _fn_test_mattermost_connection()

        assert result["server_url"] == "https://default.mm.com"
        mock_cls.assert_called_once_with("https://default.mm.com", "default-tok")


# ---- _resolve_mattermost_user_id ----

class TestResolveMattermostUserId:
    @pytest.mark.asyncio
    async def test_returns_cached_mapping(self):
        """When a mapping already exists, return its mattermost_user_id (lines 280-282)."""
        existing = MagicMock()
        existing.mattermost_user_id = "mm-cached-id"

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = existing
        mock_session.execute = AsyncMock(return_value=mock_result)

        task = Task(
            id=1, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED,
            initiator_user_id=100,
            initiator_gitlab_user_id=200,
            initiator_username="alice",
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        mock_client = AsyncMock()

        result = await _resolve_mattermost_user_id(mock_session, mock_client, task)
        assert result == "mm-cached-id"
        mock_client.get_user_by_username.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_mapping_from_api(self):
        """When no mapping exists, look up by username and create one (lines 288-309)."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        task = Task(
            id=2, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED,
            initiator_username="bob",
            initiator_user_id=10,
            initiator_gitlab_user_id=20,
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        mock_client = AsyncMock()
        mock_client.get_user_by_username.return_value = {"id": "mm-new-id", "username": "bob"}

        with patch("app.core.mattermost_notifications.utcnow", return_value=datetime(2024, 1, 1)):
            result = await _resolve_mattermost_user_id(mock_session, mock_client, task)

        assert result == "mm-new-id"
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_no_username(self):
        """When initiator_username is blank and no mapping exists, return None (line 286)."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        task = Task(
            id=3, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED,
            initiator_username="",
            initiator_user_id=10,
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        mock_client = AsyncMock()

        result = await _resolve_mattermost_user_id(mock_session, mock_client, task)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_api_returns_empty_id(self):
        """When the Mattermost API returns empty id, return None (line 290-291)."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        task = Task(
            id=4, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED,
            initiator_username="charlie",
            initiator_user_id=10,
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        mock_client = AsyncMock()
        mock_client.get_user_by_username.return_value = {"id": "", "username": "charlie"}

        result = await _resolve_mattermost_user_id(mock_session, mock_client, task)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_filters_when_all_initiator_fields_none(self):
        """No DB query when all initiator fields are None/empty (no filters built)."""
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()

        task = Task(
            id=5, project_id=1, user_prompt="x",
            status=TaskStatus.COMPLETED,
            initiator_username=None,
            initiator_user_id=None,
            initiator_gitlab_user_id=None,
        )
        task.issue_id = 1
        task.__dict__["issue"] = None
        mock_client = AsyncMock()

        result = await _resolve_mattermost_user_id(mock_session, mock_client, task)
        assert result is None
        # No DB query should have been executed (no filters)
        mock_session.execute.assert_not_awaited()


# ---- _build_attachment_fields ----

class TestBuildAttachmentFields:
    def _settings_patch(self):
        return patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(dashboard_url="https://dash"),
        )

    def test_basic_fields(self):
        """Standard fields should appear in the output (line 317+)."""
        task = Task(
            id=1, project_id=10, user_prompt="x",
            status=TaskStatus.COMPLETED,
            initiator_username="alice",
        )
        task.issue_id = 20
        task.__dict__["issue"] = SimpleNamespace(
            merge_request_iid=30,
            merge_request_url=None,
            branch_name="feat",
            target_branch="main",
        )
        with self._settings_patch():
            fields = _build_attachment_fields(
                task,
                MATTERMOST_EVENT_TASK_COMPLETED,
                [MATTERMOST_FIELD_TASK_ID, MATTERMOST_FIELD_PROJECT,
                 MATTERMOST_FIELD_STATUS, MATTERMOST_FIELD_ISSUE,
                 MATTERMOST_FIELD_MERGE_REQUEST, MATTERMOST_FIELD_INITIATOR,
                 MATTERMOST_FIELD_TASK_LINK],
                {},
            )

        titles = [f["title"] for f in fields]
        assert "任务 ID" in titles
        assert "项目" in titles
        assert "状态" in titles
        assert "任务链接" in titles

    def test_unknown_field_key_skipped(self):
        """A field key not in field_map should be silently skipped (line 349)."""
        task = Task(
            id=1, project_id=10, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = 20
        task.__dict__["issue"] = SimpleNamespace(
            merge_request_iid=None,
            merge_request_url=None,
            branch_name=None,
            target_branch=None,
        )
        with self._settings_patch():
            fields = _build_attachment_fields(
                task,
                MATTERMOST_EVENT_TASK_COMPLETED,
                ["nonexistent_key", MATTERMOST_FIELD_TASK_ID],
                {},
            )

        assert len(fields) == 1
        assert fields[0]["title"] == "任务 ID"

    def test_empty_value_skipped_for_non_exempt_fields(self):
        """Fields with '-' value should be excluded (line 352) unless they are issue or error."""
        task = Task(
            id=1, project_id=10, user_prompt="x",
            status=TaskStatus.COMPLETED,
            initiator_username=None,
        )
        task.issue_id = 20
        task.__dict__["issue"] = SimpleNamespace(
            merge_request_iid=None,
            merge_request_url=None,
            branch_name=None,
            target_branch=None,
        )
        with self._settings_patch():
            fields = _build_attachment_fields(
                task,
                MATTERMOST_EVENT_TASK_COMPLETED,
                [MATTERMOST_FIELD_BRANCH, MATTERMOST_FIELD_TARGET_BRANCH,
                 MATTERMOST_FIELD_INITIATOR],
                {},
            )

        # All three have value "-" and are not in the exempt set → all skipped
        assert len(fields) == 0

    def test_issue_with_dash_is_kept(self):
        """Issue field with '-' value should NOT be skipped (exempt)."""
        task = Task(
            id=1, project_id=10, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = None
        task.__dict__["issue"] = None
        with self._settings_patch():
            fields = _build_attachment_fields(
                task,
                MATTERMOST_EVENT_TASK_COMPLETED,
                [MATTERMOST_FIELD_ISSUE],
                {},
            )

        assert len(fields) == 1
        assert fields[0]["value"] == "-"

    def test_no_issue_shows_dash(self):
        """For tasks with no issue_id, issue should show '-'."""
        task = Task(
            id=1, project_id=10, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = None
        task.__dict__["issue"] = None
        with self._settings_patch():
            fields = _build_attachment_fields(
                task,
                MATTERMOST_EVENT_TASK_COMPLETED,
                [MATTERMOST_FIELD_ISSUE],
                {},
            )

        assert fields[0]["value"] == "-"

    def test_schedule_change_field(self):
        """When context has schedule change info, the field should be populated."""
        task = Task(
            id=1, project_id=10, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = 20
        task.__dict__["issue"] = SimpleNamespace(
            merge_request_iid=None,
            merge_request_url=None,
            branch_name=None,
            target_branch=None,
        )
        ctx = {
            "previous_scheduled_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "scheduled_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
        }
        with self._settings_patch():
            fields = _build_attachment_fields(
                task,
                MATTERMOST_EVENT_TASK_RESCHEDULED,
                [MATTERMOST_FIELD_SCHEDULE_CHANGE],
                ctx,
            )

        assert len(fields) == 1
        assert "→" in fields[0]["value"]

    def test_error_field(self):
        """Error field should be included with the error message."""
        task = Task(
            id=1, project_id=10, user_prompt="x",
            status=TaskStatus.FAILED,
            error_message="Something went wrong",
        )
        task.issue_id = 20
        task.__dict__["issue"] = SimpleNamespace(
            merge_request_iid=None,
            merge_request_url=None,
            branch_name=None,
            target_branch=None,
        )
        with self._settings_patch():
            fields = _build_attachment_fields(
                task,
                MATTERMOST_EVENT_TASK_FAILED,
                [MATTERMOST_FIELD_ERROR],
                {},
            )

        assert len(fields) == 1
        assert "Something went wrong" in fields[0]["value"]

    def test_merge_request_url_fallback(self):
        """When merge_request_iid is None, merge_request_url should be used."""
        task = Task(
            id=1, project_id=10, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = 20
        task.__dict__["issue"] = SimpleNamespace(
            merge_request_iid=None,
            merge_request_url="https://gitlab.example.com/mr/1",
            branch_name=None,
            target_branch=None,
        )
        with self._settings_patch():
            fields = _build_attachment_fields(
                task,
                MATTERMOST_EVENT_TASK_COMPLETED,
                [MATTERMOST_FIELD_MERGE_REQUEST],
                {},
            )

        assert fields[0]["value"] == "https://gitlab.example.com/mr/1"


# ---- _build_card_markdown ----

class TestBuildCardMarkdown:
    def _settings_patch(self):
        return patch(
            "app.core.mattermost_notifications.get_effective_settings",
            return_value=SimpleNamespace(dashboard_url="https://dash"),
        )

    def test_basic_markdown(self):
        """Card markdown should include task ID, project, and status."""
        task = Task(
            id=1, project_id=10, user_prompt="x",
            status=TaskStatus.COMPLETED,
        )
        task.issue_id = 20
        task.__dict__["issue"] = SimpleNamespace(
            merge_request_iid=None,
            merge_request_url=None,
            branch_name=None,
            target_branch=None,
        )
        with self._settings_patch():
            md = _build_card_markdown(task, MATTERMOST_EVENT_TASK_COMPLETED, {})

        assert "任务完成" in md
        assert "#1" in md
        assert "#10" in md
        assert "completed" in md

    def test_includes_optional_fields(self):
        """Card should include MR, initiator, scheduled_at, error when present (lines 374-385)."""
        task = Task(
            id=2, project_id=10, user_prompt="x",
            status=TaskStatus.FAILED,
            initiator_username="bob",
            scheduled_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            error_message="Out of memory",
        )
        task.issue_id = 20
        task.__dict__["issue"] = SimpleNamespace(
            merge_request_iid=30,
            merge_request_url=None,
            branch_name=None,
            target_branch=None,
        )
        ctx = {
            "previous_scheduled_at": datetime(2024, 5, 1, tzinfo=timezone.utc),
            "scheduled_at": datetime(2024, 6, 1, tzinfo=timezone.utc),
        }
        with self._settings_patch():
            md = _build_card_markdown(task, MATTERMOST_EVENT_TASK_FAILED, ctx)

        assert "!30" in md           # line 374
        assert "bob" in md            # line 376 (initiator_username)
        assert "当前预约时间" in md    # line 378 (scheduled_at)
        assert "时间变更" in md        # line 380 (schedule change)
        assert "Out of memory" in md  # line 385 (error_message)


if __name__ == "__main__":
    unittest.main()
