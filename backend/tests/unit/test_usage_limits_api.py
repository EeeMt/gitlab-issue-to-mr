#!/usr/bin/env python3
"""Unit tests for usage limits API endpoints."""

import os
import sys
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api.usage_limits import (
    build_current_user_usage_summary,
    list_usage_limit_users,
    update_admin_usage_limit_default,
    update_usage_limit_user,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user, require_authenticated_user
from app.main import app
from app.models import UsageLimitPolicy


def _make_mock_user(
    *,
    id=1,
    username="testuser",
    display_name="Test User",
    email="test@example.com",
    platform_role="platform_user",
):
    user = MagicMock()
    user.id = id
    user.username = username
    user.display_name = display_name
    user.email = email
    user.platform_role = platform_role
    return user


def _make_policy(
    *,
    scope_type="user",
    user_id=7,
    daily_tokens_mode="inherit",
    daily_tokens_value=None,
    weekly_tokens_mode="inherit",
    weekly_tokens_value=None,
    daily_tasks_mode="inherit",
    daily_tasks_value=None,
    weekly_tasks_mode="inherit",
    weekly_tasks_value=None,
):
    policy = UsageLimitPolicy(
        scope_type=scope_type,
        user_id=user_id,
        daily_tokens_mode=daily_tokens_mode,
        daily_tokens_value=daily_tokens_value,
        weekly_tokens_mode=weekly_tokens_mode,
        weekly_tokens_value=weekly_tokens_value,
        daily_tasks_mode=daily_tasks_mode,
        daily_tasks_value=daily_tasks_value,
        weekly_tasks_mode=weekly_tasks_mode,
        weekly_tasks_value=weekly_tasks_value,
    )
    policy.id = 1
    policy.created_at = datetime(2026, 4, 27)
    policy.updated_at = datetime(2026, 4, 27)
    return policy


class UsageLimitsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        default_result = MagicMock()
        default_result.scalar_one_or_none.return_value = None
        default_result.scalars.return_value.all.return_value = []
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(return_value=default_result)
        self.mock_db.get = AsyncMock()
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.refresh = AsyncMock()

        async def override_db():
            yield self.mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_user] = lambda: _make_mock_user(id=7)
        app.dependency_overrides[require_admin_user] = lambda: _make_mock_user(
            id=1,
            username="admin",
            platform_role="platform_admin",
        )

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_get_my_usage_summary_route_exists(self) -> None:
        with patch(
            "app.api.usage_limits.build_current_user_usage_summary",
            new=AsyncMock(
                return_value={
                    "user_id": 7,
                    "usage": {
                        "daily_tokens": 1200,
                        "weekly_tokens": 3200,
                        "daily_tasks": 1,
                        "weekly_tasks": 3,
                    },
                    "limits": {
                        "daily_tokens": {"mode": "custom", "value": 5000},
                        "weekly_tokens": {"mode": "custom", "value": 20000},
                        "daily_tasks": {"mode": "custom", "value": 5},
                        "weekly_tasks": {"mode": "custom", "value": 20},
                    },
                    "reset_at": {
                        "daily": "2026-04-28T00:00:00+08:00",
                        "weekly": "2026-05-04T00:00:00+08:00",
                    },
                    "is_over_limit": False,
                    "severity": "normal",
                }
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/usage/me")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "user_id": 7,
                "usage": {
                    "daily_tokens": 1200,
                    "weekly_tokens": 3200,
                    "daily_tasks": 1,
                    "weekly_tasks": 3,
                },
                "limits": {
                    "daily_tokens": {"mode": "custom", "value": 5000},
                    "weekly_tokens": {"mode": "custom", "value": 20000},
                    "daily_tasks": {"mode": "custom", "value": 5},
                    "weekly_tasks": {"mode": "custom", "value": 20},
                },
                "reset_at": {
                    "daily": "2026-04-28T00:00:00+08:00",
                    "weekly": "2026-05-04T00:00:00+08:00",
                },
                "is_over_limit": False,
                "severity": "normal",
            },
        )

    def test_get_admin_usage_limit_default_returns_serialized_policy(self) -> None:
        with patch(
            "app.api.usage_limits.get_admin_usage_limit_default",
            new=AsyncMock(
                return_value={
                    "daily_tokens": {"mode": "custom", "value": 5000},
                    "weekly_tokens": {"mode": "custom", "value": 20000},
                    "daily_tasks": {"mode": "custom", "value": 5},
                    "weekly_tasks": {"mode": "unlimited", "value": None},
                }
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/admin/usage-limits/default")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["weekly_tasks"]["mode"], "unlimited")

    def test_patch_admin_usage_limit_default_updates_policy(self) -> None:
        with patch(
            "app.api.usage_limits.update_admin_usage_limit_default",
            new=AsyncMock(
                return_value={
                    "daily_tokens": {"mode": "custom", "value": 5000},
                    "weekly_tokens": {"mode": "custom", "value": 20000},
                    "daily_tasks": {"mode": "custom", "value": 5},
                    "weekly_tasks": {"mode": "unlimited", "value": None},
                }
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.patch(
                "/api/admin/usage-limits/default",
                json={
                    "daily_tokens": {"mode": "custom", "value": 5000},
                    "weekly_tokens": {"mode": "custom", "value": 20000},
                    "daily_tasks": {"mode": "custom", "value": 5},
                    "weekly_tasks": {"mode": "unlimited", "value": None},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["daily_tokens"]["value"], 5000)

    def test_patch_admin_usage_limit_default_rejects_inherit_mode(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.patch(
            "/api/admin/usage-limits/default",
            json={
                "daily_tokens": {"mode": "inherit", "value": None},
                "weekly_tokens": {"mode": "custom", "value": 20000},
                "daily_tasks": {"mode": "custom", "value": 5},
                "weekly_tasks": {"mode": "unlimited", "value": None},
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_patch_admin_usage_limit_default_rejects_partial_payload(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.patch(
            "/api/admin/usage-limits/default",
            json={
                "daily_tokens": {"mode": "custom", "value": 5000},
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_patch_admin_usage_limit_default_rejects_custom_without_value(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.patch(
            "/api/admin/usage-limits/default",
            json={
                "daily_tokens": {"mode": "custom", "value": None},
                "weekly_tokens": {"mode": "custom", "value": 20000},
                "daily_tasks": {"mode": "custom", "value": 5},
                "weekly_tasks": {"mode": "unlimited", "value": None},
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_get_admin_usage_limit_users_returns_usage_rows(self) -> None:
        with patch(
            "app.api.usage_limits.list_usage_limit_users",
            new=AsyncMock(
                return_value=[
                    {
                        "user_id": 7,
                        "username": "alice",
                        "display_name": "Alice",
                        "usage": {
                            "daily_tokens": 1200,
                            "weekly_tokens": 3200,
                            "daily_tasks": 1,
                            "weekly_tasks": 3,
                        },
                        "limits": {
                            "daily_tokens": {"mode": "custom", "value": 5000},
                            "weekly_tokens": {"mode": "custom", "value": 20000},
                            "daily_tasks": {"mode": "custom", "value": 5},
                            "weekly_tasks": {"mode": "custom", "value": 20},
                        },
                        "overrides": {
                            "daily_tokens": {"mode": "inherit", "value": None},
                            "weekly_tokens": {"mode": "custom", "value": 12000},
                            "daily_tasks": {"mode": "inherit", "value": None},
                            "weekly_tasks": {"mode": "unlimited", "value": None},
                        },
                        "reset_at": {
                            "daily": "2026-04-28T00:00:00+08:00",
                            "weekly": "2026-05-04T00:00:00+08:00",
                        },
                    }
                ]
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/admin/usage-limits/users")

        self.assertEqual(response.status_code, 200)
        row = response.json()[0]
        self.assertEqual(row["username"], "alice")
        self.assertEqual(row["overrides"]["weekly_tasks"]["mode"], "unlimited")

    def test_patch_admin_usage_limit_user_updates_override(self) -> None:
        with patch(
            "app.api.usage_limits.update_usage_limit_user",
            new=AsyncMock(
                return_value={
                    "user_id": 7,
                    "username": "alice",
                    "display_name": "Alice",
                    "usage": {
                        "daily_tokens": 1200,
                        "weekly_tokens": 3200,
                        "daily_tasks": 1,
                        "weekly_tasks": 3,
                    },
                    "limits": {
                        "daily_tokens": {"mode": "custom", "value": 5000},
                        "weekly_tokens": {"mode": "custom", "value": 20000},
                        "daily_tasks": {"mode": "custom", "value": 5},
                        "weekly_tasks": {"mode": "custom", "value": 20},
                    },
                    "overrides": {
                        "daily_tokens": {"mode": "custom", "value": 100000},
                        "weekly_tokens": {"mode": "inherit", "value": None},
                        "daily_tasks": {"mode": "unlimited", "value": None},
                        "weekly_tasks": {"mode": "custom", "value": 20},
                    },
                    "reset_at": {
                        "daily": "2026-04-28T00:00:00+08:00",
                        "weekly": "2026-05-04T00:00:00+08:00",
                    },
                }
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.patch(
                "/api/admin/usage-limits/users/7",
                json={
                    "daily_tokens": {"mode": "custom", "value": 100000},
                    "weekly_tokens": {"mode": "inherit", "value": None},
                    "daily_tasks": {"mode": "unlimited", "value": None},
                    "weekly_tasks": {"mode": "custom", "value": 20},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["overrides"]["daily_tokens"]["value"], 100000)


class UsageLimitsApiHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_current_user_usage_summary_returns_structured_payload(self) -> None:
        db = MagicMock()
        current_user = _make_mock_user(id=7, username="alice", display_name="Alice")
        mock_service = MagicMock()
        mock_service.get_current_usage_totals = AsyncMock(
            return_value={
                "daily_tokens": 1200,
                "weekly_tokens": 3200,
                "daily_tasks": 1,
                "weekly_tasks": 3,
            }
        )
        mock_service.resolve_effective_limits = AsyncMock(
            return_value={
                "daily_tokens": MagicMock(mode="custom", value=5000, is_unlimited=False),
                "weekly_tokens": MagicMock(mode="custom", value=20000, is_unlimited=False),
                "daily_tasks": MagicMock(mode="custom", value=5, is_unlimited=False),
                "weekly_tasks": MagicMock(mode="custom", value=20, is_unlimited=False),
            }
        )

        with patch("app.api.usage_limits.get_usage_quota_service", return_value=mock_service):
            summary = await build_current_user_usage_summary(
                db,
                current_user,
                now=datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
            )

        self.assertEqual(summary["user_id"], 7)
        self.assertFalse(summary["is_over_limit"])
        self.assertEqual(summary["severity"], "normal")
        self.assertEqual(summary["reset_at"]["daily"], "2026-04-28T00:00:00+00:00")
        self.assertEqual(summary["limits"]["daily_tokens"]["value"], 5000)

    async def test_update_admin_usage_limit_default_creates_policy_row(self) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.add = MagicMock()
        payload = {
            "daily_tokens": {"mode": "custom", "value": 5000},
            "weekly_tokens": {"mode": "custom", "value": 20000},
            "daily_tasks": {"mode": "custom", "value": 5},
            "weekly_tasks": {"mode": "unlimited", "value": None},
        }

        response = await update_admin_usage_limit_default(db, payload)

        added_policy = db.add.call_args.args[0]
        self.assertEqual(added_policy.scope_type, "system_default")
        self.assertIsNone(added_policy.user_id)
        self.assertEqual(added_policy.daily_tokens_value, 5000)
        self.assertEqual(response["weekly_tasks"]["mode"], "unlimited")

    async def test_update_admin_usage_limit_default_clears_value_for_unlimited(self) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.add = MagicMock()

        response = await update_admin_usage_limit_default(
            db,
            {
                "daily_tokens": {"mode": "custom", "value": 5000},
                "weekly_tokens": {"mode": "custom", "value": 20000},
                "daily_tasks": {"mode": "custom", "value": 5},
                "weekly_tasks": {"mode": "unlimited", "value": 20},
            },
        )

        added_policy = db.add.call_args.args[0]
        self.assertIsNone(added_policy.weekly_tasks_value)
        self.assertIsNone(response["weekly_tasks"]["value"])

    async def test_list_usage_limit_users_builds_rows_from_users_and_overrides(self) -> None:
        user = _make_mock_user(id=7, username="alice", display_name="Alice")
        user_result = MagicMock()
        user_result.scalars.return_value.all.return_value = [user]
        policy_result = MagicMock()
        policy_result.scalar_one_or_none.return_value = _make_policy(
            user_id=7,
            daily_tokens_mode="custom",
            daily_tokens_value=100000,
            weekly_tokens_mode="inherit",
            weekly_tokens_value=None,
            daily_tasks_mode="unlimited",
            daily_tasks_value=None,
            weekly_tasks_mode="inherit",
            weekly_tasks_value=None,
        )
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[user_result, policy_result])
        mock_service = MagicMock()
        mock_service.get_current_usage_totals = AsyncMock(
            return_value={
                "daily_tokens": 1200,
                "weekly_tokens": 3200,
                "daily_tasks": 1,
                "weekly_tasks": 3,
            }
        )
        mock_service.resolve_effective_limits = AsyncMock(
            return_value={
                "daily_tokens": MagicMock(mode="custom", value=100000, is_unlimited=False),
                "weekly_tokens": MagicMock(mode="custom", value=500000, is_unlimited=False),
                "daily_tasks": MagicMock(mode="unlimited", value=None, is_unlimited=True),
                "weekly_tasks": MagicMock(mode="custom", value=20, is_unlimited=False),
            }
        )

        with patch("app.api.usage_limits.get_usage_quota_service", return_value=mock_service):
            rows = await list_usage_limit_users(
                db,
                now=datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["username"], "alice")
        self.assertEqual(rows[0]["overrides"]["daily_tokens"]["value"], 100000)
        self.assertEqual(rows[0]["limits"]["weekly_tasks"]["value"], 20)

    async def test_update_usage_limit_user_creates_override_and_returns_row(self) -> None:
        user = _make_mock_user(id=7, username="alice", display_name="Alice")
        user_policy_missing = MagicMock()
        user_policy_missing.scalar_one_or_none.return_value = None
        user_policy_created = MagicMock()
        user_policy_created.scalar_one_or_none.return_value = _make_policy(
            user_id=7,
            daily_tokens_mode="custom",
            daily_tokens_value=100000,
            weekly_tokens_mode="inherit",
            weekly_tokens_value=None,
            daily_tasks_mode="unlimited",
            daily_tasks_value=None,
            weekly_tasks_mode="custom",
            weekly_tasks_value=20,
        )
        db = MagicMock()
        db.get = AsyncMock(return_value=user)
        db.execute = AsyncMock(side_effect=[user_policy_missing, user_policy_created])
        db.add = MagicMock()
        mock_service = MagicMock()
        mock_service.get_current_usage_totals = AsyncMock(
            return_value={
                "daily_tokens": 1200,
                "weekly_tokens": 3200,
                "daily_tasks": 1,
                "weekly_tasks": 3,
            }
        )
        mock_service.resolve_effective_limits = AsyncMock(
            return_value={
                "daily_tokens": MagicMock(mode="custom", value=100000, is_unlimited=False),
                "weekly_tokens": MagicMock(mode="custom", value=500000, is_unlimited=False),
                "daily_tasks": MagicMock(mode="unlimited", value=None, is_unlimited=True),
                "weekly_tasks": MagicMock(mode="custom", value=20, is_unlimited=False),
            }
        )
        payload = {
            "daily_tokens": {"mode": "custom", "value": 100000},
            "weekly_tokens": {"mode": "inherit", "value": None},
            "daily_tasks": {"mode": "unlimited", "value": None},
            "weekly_tasks": {"mode": "custom", "value": 20},
        }

        with patch("app.api.usage_limits.get_usage_quota_service", return_value=mock_service):
            row = await update_usage_limit_user(
                db,
                7,
                payload,
                now=datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
            )

        added_policy = db.add.call_args.args[0]
        self.assertEqual(added_policy.scope_type, "user")
        self.assertEqual(added_policy.user_id, 7)
        self.assertEqual(row["overrides"]["weekly_tasks"]["value"], 20)

    async def test_update_usage_limit_user_clears_value_for_inherit(self) -> None:
        user = _make_mock_user(id=7, username="alice", display_name="Alice")
        user_policy_missing = MagicMock()
        user_policy_missing.scalar_one_or_none.return_value = None
        user_policy_created = MagicMock()
        user_policy_created.scalar_one_or_none.return_value = _make_policy(
            user_id=7,
            daily_tokens_mode="inherit",
            daily_tokens_value=None,
            weekly_tokens_mode="inherit",
            weekly_tokens_value=None,
            daily_tasks_mode="inherit",
            daily_tasks_value=None,
            weekly_tasks_mode="inherit",
            weekly_tasks_value=None,
        )
        db = MagicMock()
        db.get = AsyncMock(return_value=user)
        db.execute = AsyncMock(side_effect=[user_policy_missing, user_policy_created])
        db.add = MagicMock()
        mock_service = MagicMock()
        mock_service.get_current_usage_totals = AsyncMock(
            return_value={
                "daily_tokens": 1200,
                "weekly_tokens": 3200,
                "daily_tasks": 1,
                "weekly_tasks": 3,
            }
        )
        mock_service.resolve_effective_limits = AsyncMock(
            return_value={
                "daily_tokens": MagicMock(mode="custom", value=100000, is_unlimited=False),
                "weekly_tokens": MagicMock(mode="custom", value=500000, is_unlimited=False),
                "daily_tasks": MagicMock(mode="custom", value=5, is_unlimited=False),
                "weekly_tasks": MagicMock(mode="custom", value=20, is_unlimited=False),
            }
        )

        with patch("app.api.usage_limits.get_usage_quota_service", return_value=mock_service):
            row = await update_usage_limit_user(
                db,
                7,
                {
                    "daily_tokens": {"mode": "inherit", "value": 100000},
                    "weekly_tokens": {"mode": "inherit", "value": None},
                    "daily_tasks": {"mode": "inherit", "value": None},
                    "weekly_tasks": {"mode": "inherit", "value": 20},
                },
                now=datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
            )

        added_policy = db.add.call_args.args[0]
        self.assertIsNone(added_policy.daily_tokens_value)
        self.assertIsNone(added_policy.weekly_tasks_value)
        self.assertIsNone(row["overrides"]["daily_tokens"]["value"])

    async def test_update_usage_limit_user_raises_404_when_user_missing(self) -> None:
        db = MagicMock()
        db.get = AsyncMock(return_value=None)

        with self.assertRaises(HTTPException) as ctx:
            await update_usage_limit_user(
                db,
                999,
                {
                    "daily_tokens": {"mode": "custom", "value": 100000},
                    "weekly_tokens": {"mode": "inherit", "value": None},
                    "daily_tasks": {"mode": "unlimited", "value": None},
                    "weekly_tasks": {"mode": "custom", "value": 20},
                },
            )

        self.assertEqual(ctx.exception.status_code, 404)
