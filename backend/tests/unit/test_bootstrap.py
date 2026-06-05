#!/usr/bin/env python3
"""Unit tests for bootstrap core logic."""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.bootstrap import (
    get_bootstrap_state,
    get_initial_admin,
    initialize_system,
    is_system_initialized,
)
from app.models import SystemBootstrap, User


def _make_db(scalar_value=None):
    """Helper: create a mock AsyncSession that returns scalar_value on .scalar_one_or_none()."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_value
    db = MagicMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


class GetBootstrapStateTests(unittest.IsolatedAsyncioTestCase):
    """Tests for get_bootstrap_state."""

    async def test_get_bootstrap_state_returns_existing_record(self) -> None:
        """When a SystemBootstrap record exists it should be returned directly."""
        existing = SystemBootstrap(id=1, initialized=False)
        db = _make_db(scalar_value=existing)

        result = await get_bootstrap_state(db)

        self.assertIs(result, existing)
        db.add.assert_not_called()

    async def test_get_bootstrap_state_creates_new_if_not_found(self) -> None:
        """When no record exists, a new SystemBootstrap should be created and added."""
        db = _make_db(scalar_value=None)

        await get_bootstrap_state(db)

        db.add.assert_called_once()
        added = db.add.call_args.args[0]
        self.assertIsInstance(added, SystemBootstrap)
        self.assertEqual(added.id, 1)
        self.assertFalse(added.initialized)
        db.flush.assert_awaited_once()


class IsSystemInitializedTests(unittest.IsolatedAsyncioTestCase):
    """Tests for is_system_initialized."""

    async def test_is_system_initialized_returns_false_when_not_initialized(self) -> None:
        """Should return False when bootstrap.initialized is False."""
        bootstrap = MagicMock()
        bootstrap.initialized = False
        db = _make_db(scalar_value=bootstrap)

        result = await is_system_initialized(db)

        self.assertFalse(result)

    async def test_is_system_initialized_returns_true_when_initialized(self) -> None:
        """Should return True when bootstrap.initialized is True."""
        bootstrap = MagicMock()
        bootstrap.initialized = True
        db = _make_db(scalar_value=bootstrap)

        result = await is_system_initialized(db)

        self.assertTrue(result)


class InitializeSystemTests(unittest.IsolatedAsyncioTestCase):
    """Tests for initialize_system."""

    async def test_initialize_system_sets_initialized_true(self) -> None:
        """initialize_system should set bootstrap.initialized = True and store admin user id."""
        bootstrap = MagicMock()
        bootstrap.initialized = False
        bootstrap.initial_admin_user_id = None
        db = _make_db(scalar_value=bootstrap)

        admin_user = MagicMock()
        admin_user.id = 42

        result = await initialize_system(db, admin_user)

        self.assertTrue(result.initialized)
        self.assertEqual(result.initial_admin_user_id, 42)

    async def test_initialize_system_sets_initialized_at(self) -> None:
        """initialize_system should set bootstrap.initialized_at to a non-None value."""
        bootstrap = MagicMock()
        bootstrap.initialized = False
        bootstrap.initialized_at = None
        db = _make_db(scalar_value=bootstrap)

        admin_user = MagicMock()
        admin_user.id = 7

        result = await initialize_system(db, admin_user)

        self.assertIsNotNone(result.initialized_at)


class GetInitialAdminTests(unittest.IsolatedAsyncioTestCase):
    """Tests for get_initial_admin."""

    async def test_get_initial_admin_returns_none_when_no_admin_user_id(self) -> None:
        """Should return None when bootstrap.initial_admin_user_id is None."""
        bootstrap = MagicMock()
        bootstrap.initial_admin_user_id = None
        db = _make_db(scalar_value=bootstrap)

        result = await get_initial_admin(db)

        self.assertIsNone(result)

    async def test_get_initial_admin_returns_user_when_configured(self) -> None:
        """Should return the User when initial_admin_user_id is set."""
        user = User(id=42, username="admin")
        bootstrap = MagicMock()
        bootstrap.initial_admin_user_id = 42

        # First call returns bootstrap, second call returns user
        mock_result_bootstrap = MagicMock()
        mock_result_bootstrap.scalar_one_or_none.return_value = bootstrap

        mock_result_user = MagicMock()
        mock_result_user.scalar_one_or_none.return_value = user

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[mock_result_bootstrap, mock_result_user])
        db.add = MagicMock()
        db.flush = AsyncMock()

        result = await get_initial_admin(db)

        self.assertIs(result, user)


if __name__ == "__main__":
    unittest.main()
