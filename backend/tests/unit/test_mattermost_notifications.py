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
from app.models import MattermostNotificationProfile, Task, TaskStatus


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
            issue_iid=34,
            user_prompt="ship it",
            branch_name="feature/demo",
            target_branch="main",
            status=TaskStatus.COMPLETED,
            initiator_username="alice",
        )
        profile = MattermostNotificationProfile(
            id=1,
            name="Channel",
            enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_CHANNEL,
            team_name="engineering",
            channel_name="gimr",
            mention_in_channel=True,
            event_types_json='["task_completed"]',
            field_keys_json='["task_id","status"]',
            send_for_manual_tasks=True,
        )
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [profile])
        )
        mock_client = AsyncMock()
        mock_client.get_channel_by_name.return_value = {"id": "channel-1"}

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

        mock_client.get_channel_by_name.assert_awaited_once_with("engineering", "gimr")
        create_post_args = mock_client.create_post.await_args.args
        self.assertEqual(create_post_args[0], "channel-1")
        self.assertIn("@alice", create_post_args[1])
        self.assertEqual(mock_session.commit.await_count, 1)

    async def test_notify_task_event_skips_dm_when_initiator_missing(self) -> None:
        task = Task(
            id=9,
            project_id=12,
            issue_iid=34,
            user_prompt="ship it",
            branch_name="feature/demo",
            target_branch="main",
            status=TaskStatus.FAILED,
            initiator_username=None,
        )
        profile = MattermostNotificationProfile(
            id=2,
            name="DM",
            enabled=True,
            target_type=MATTERMOST_TARGET_TYPE_INITIATOR_DM,
            team_name=None,
            channel_name=None,
            mention_in_channel=False,
            event_types_json='["task_failed"]',
            field_keys_json='["task_id","status"]',
            send_for_manual_tasks=True,
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


if __name__ == "__main__":
    unittest.main()
